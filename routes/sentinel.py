"""LEXARYS SENTINEL - Surveillance continue d'entreprises
Detecte changements de gouvernance, procedures collectives, evenements BODACC,
nouveaux marches publics gagnes, alertes ICPE, etc.
Genere des alertes critiques pour avocats d'affaires / compliance officers.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import httpx, asyncio, time, json, re
from database import supabase
from auth import get_current_user

router = APIRouter(prefix="/sentinel", tags=["sentinel"])

API_GOUV = "https://recherche-entreprises.api.gouv.fr/search"
BODACC_API = "https://bodacc-datadila.opendatasoft.com/api/records/1.0/search/"
DECP_API = "https://www.data.gouv.fr/api/2/datasets/61308a1ec57d8efc220ce17a/resources/"


# ========== MODELES ==========
class WatchlistAdd(BaseModel):
    siren: str
    raison_sociale: Optional[str] = None
    type_surveillance: Optional[str] = "standard"
    client_id: Optional[str] = None
    dossier_id: Optional[str] = None
    watch_bodacc: bool = True
    watch_dirigeants: bool = True
    watch_capital: bool = True
    watch_rbe: bool = True
    watch_procedures: bool = True
    watch_marches_publics: bool = True
    watch_icpe: bool = False
    watch_score: bool = True
    notes: Optional[str] = None


class WatchlistUpdate(BaseModel):
    type_surveillance: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    watch_bodacc: Optional[bool] = None
    watch_dirigeants: Optional[bool] = None
    watch_capital: Optional[bool] = None
    watch_procedures: Optional[bool] = None
    watch_marches_publics: Optional[bool] = None
    watch_icpe: Optional[bool] = None


# ========== HELPERS ==========
async def fetch_entreprise(siren: str) -> Dict[str, Any]:
    """Recupere la fiche entreprise via recherche-entreprises.api.gouv.fr"""
    async with httpx.AsyncClient(timeout=10.0) as cx:
        r = await cx.get(API_GOUV, params={"q": siren, "page": 1, "per_page": 1})
        if r.status_code != 200:
            return {}
        data = r.json()
        results = data.get("results", [])
        return results[0] if results else {}


async def fetch_bodacc_recent(siren: str, days: int = 30) -> List[Dict[str, Any]]:
    """Recupere les annonces BODACC recentes pour ce SIREN."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "dataset": "annonces-commerciales",
        "q": siren,
        "rows": 50,
        "refine.dateparution": ">=" + since,
        "sort": "-dateparution",
    }
    async with httpx.AsyncClient(timeout=10.0) as cx:
        try:
            r = await cx.get(BODACC_API, params=params)
            if r.status_code != 200:
                return []
            return [rec.get("fields", {}) for rec in r.json().get("records", [])]
        except Exception:
            return []


def snapshot_signature(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait une signature stable du fiche entreprise pour diff."""
    if not data:
        return {}
    siege = data.get("siege") or {}
    dirs = data.get("dirigeants") or []
    return {
        "nom_complet": data.get("nom_complet"),
        "nom_raison_sociale": data.get("nom_raison_sociale"),
        "etat_administratif": data.get("etat_administratif"),
        "nombre_etablissements_ouverts": data.get("nombre_etablissements_ouverts"),
        "nombre_etablissements": data.get("nombre_etablissements"),
        "tranche_effectif_salarie": data.get("tranche_effectif_salarie"),
        "nature_juridique": data.get("nature_juridique"),
        "categorie_entreprise": data.get("categorie_entreprise"),
        "date_creation": data.get("date_creation"),
        "activite_principale": data.get("activite_principale"),
        "siege_adresse": siege.get("adresse"),
        "siege_code_postal": siege.get("code_postal"),
        "siege_commune": siege.get("libelle_commune"),
        "siege_siret": siege.get("siret"),
        "dirigeants_count": len(dirs),
        "dirigeants_noms": sorted([
            f"{(d.get('nom') or '').upper()} {(d.get('prenoms') or '').upper()}".strip()
            for d in dirs if isinstance(d, dict)
        ]),
        "dirigeants_detail": [{"nom": d.get("nom"), "prenoms": d.get("prenoms"), "qualite": d.get("qualite")} for d in dirs if isinstance(d, dict)][:20],
    }
    return {
        "etat_administratif": data.get("etat_administratif"),
        "nombre_etablissements_ouverts": data.get("nombre_etablissements_ouverts"),
        "tranche_effectif_salarie": data.get("tranche_effectif_salarie"),
        "nature_juridique": data.get("nature_juridique"),
        "siege_adresse": (data.get("siege") or {}).get("adresse"),
        "siege_code_postal": (data.get("siege") or {}).get("code_postal"),
        "dirigeants_count": len(data.get("dirigeants") or []),
        "dirigeants_noms": sorted([
            f"{(d.get('nom') or '').upper()} {(d.get('prenoms') or '').upper()}"
            for d in (data.get("dirigeants") or [])
        ]),
        "complements_economique_sociale": (data.get("complements") or {}).get("est_economique_sociale_solidaire"),
        "annee_categorie_entreprise": data.get("annee_categorie_entreprise"),
    }


def diff_snapshots(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compare deux snapshots et retourne la liste des changements significatifs."""
    if not old:
        return []
    changes = []
    if old.get("etat_administratif") != new.get("etat_administratif"):
        sev = "critical" if new.get("etat_administratif") == "C" else "warning"
        changes.append({
            "category": "etat_administratif",
            "severity": sev,
            "title": f"Etat administratif modifie : {old.get('etat_administratif')} -> {new.get('etat_administratif')}",
            "details": {"avant": old.get("etat_administratif"), "apres": new.get("etat_administratif")},
        })
    if old.get("dirigeants_noms") != new.get("dirigeants_noms"):
        added = set(new.get("dirigeants_noms", [])) - set(old.get("dirigeants_noms", []))
        removed = set(old.get("dirigeants_noms", [])) - set(new.get("dirigeants_noms", []))
        if added or removed:
            changes.append({
                "category": "dirigeants",
                "severity": "warning",
                "title": "Changement dans la gouvernance",
                "details": {"ajouts": list(added), "retraits": list(removed)},
            })
    if old.get("tranche_effectif_salarie") != new.get("tranche_effectif_salarie"):
        changes.append({
            "category": "effectif",
            "severity": "info",
            "title": f"Tranche d'effectif modifiee : {old.get('tranche_effectif_salarie')} -> {new.get('tranche_effectif_salarie')}",
            "details": {},
        })
    if old.get("siege_adresse") != new.get("siege_adresse"):
        changes.append({
            "category": "siege",
            "severity": "info",
            "title": "Changement d'adresse du siege",
            "details": {"avant": old.get("siege_adresse"), "apres": new.get("siege_adresse")},
        })
    if old.get("nombre_etablissements_ouverts") != new.get("nombre_etablissements_ouverts"):
        delta = (new.get("nombre_etablissements_ouverts") or 0) - (old.get("nombre_etablissements_ouverts") or 0)
        if abs(delta) > 0:
            sev = "warning" if delta < 0 else "info"
            changes.append({
                "category": "etablissements",
                "severity": sev,
                "title": f"Nombre d'etablissements : {delta:+d}",
                "details": {"avant": old.get("nombre_etablissements_ouverts"), "apres": new.get("nombre_etablissements_ouverts")},
            })
    return changes


def bodacc_to_alerts(annonces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convertit annonces BODACC en alertes."""
    alerts = []
    for a in annonces:
        fam = (a.get("familleavis") or "").lower()
        listep = (a.get("listepersonnes") or "")
        date_pub = a.get("dateparution")
        text = (a.get("publicationavis_facette") or "") + " " + (a.get("typeavis") or "")
        if "redressement" in text.lower() or "liquidation" in text.lower() or "sauvegarde" in text.lower():
            alerts.append({
                "category": "procedure_collective",
                "severity": "critical",
                "title": "Procedure collective annoncee au BODACC",
                "description": (a.get("typeavis") or "") + " - " + (a.get("publicationavis_facette") or ""),
                "source": "BODACC",
                "details": {"date_parution": date_pub, "tribunal": a.get("tribunal"), "raw": a},
            })
        elif "modification" in fam:
            alerts.append({
                "category": "bodacc_modification",
                "severity": "info",
                "title": "Modification publiee au BODACC",
                "description": a.get("typeavis") or "",
                "source": "BODACC",
                "details": {"date_parution": date_pub, "raw": a},
            })
        elif "vente" in fam or "cession" in fam:
            alerts.append({
                "category": "cession",
                "severity": "warning",
                "title": "Vente/cession publiee au BODACC",
                "description": a.get("typeavis") or "",
                "source": "BODACC",
                "details": {"date_parution": date_pub, "raw": a},
            })
        elif "depot" in fam.replace("\u00f4","o") or "depots" in fam.replace("\u00f4","o"):
            # Depots comptes
            alerts.append({
                "category": "depots_comptes",
                "severity": "info",
                "title": "Depot des comptes annuels",
                "description": a.get("typeavis") or "",
                "source": "BODACC",
                "details": {"date_parution": date_pub, "raw": a},
            })
        elif "creation" in fam:
            continue  # ignore creations sur surveillance existante
        else:
            alerts.append({
                "category": "bodacc_autre",
                "severity": "info",
                "title": "Annonce BODACC",
                "description": (a.get("typeavis") or "") + " - " + fam,
                "source": "BODACC",
                "details": {"date_parution": date_pub, "raw": a},
            })
    return alerts


# ========== CRUD WATCHLIST ==========
@router.get("")
async def list_watchlist(user=Depends(get_current_user), include_inactive: bool = False):
    q = supabase.table("sentinel_watchlist").select("*").eq("user_id", user["id"])
    if not include_inactive:
        q = q.eq("is_active", True)
    q = q.order("created_at", desc=True)
    res = q.execute()
    items = res.data or []
    # Joindre le compte d'alertes non acquittees
    for it in items:
        ar = supabase.table("sentinel_alerts").select("id,severity").eq("watchlist_id", it["id"]).eq("is_acknowledged", False).execute()
        alerts = ar.data or []
        it["alerts_open"] = len(alerts)
        it["alerts_critical"] = sum(1 for a in alerts if a.get("severity") == "critical")
        it["alerts_warning"] = sum(1 for a in alerts if a.get("severity") == "warning")
    return items


@router.post("")
async def add_to_watchlist(body: WatchlistAdd, user=Depends(get_current_user)):
    # Verifier que le siren n'est pas deja surveille
    existing = supabase.table("sentinel_watchlist").select("id").eq("user_id", user["id"]).eq("siren", body.siren).execute()
    if existing.data:
        raise HTTPException(400, "Cette entreprise est deja sous surveillance")
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user["id"]
    res = supabase.table("sentinel_watchlist").insert(data).execute()
    return res.data[0] if res.data else {}


@router.put("/{watchlist_id}")
async def update_watchlist(watchlist_id: str, body: WatchlistUpdate, user=Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    res = supabase.table("sentinel_watchlist").update(data).eq("id", watchlist_id).eq("user_id", user["id"]).execute()
    return res.data[0] if res.data else {}


@router.delete("/{watchlist_id}")
async def delete_watchlist(watchlist_id: str, user=Depends(get_current_user)):
    supabase.table("sentinel_watchlist").delete().eq("id", watchlist_id).eq("user_id", user["id"]).execute()
    return {"ok": True}


# ========== ALERTES ==========
@router.get("/alerts")
async def list_alerts(user=Depends(get_current_user), severity: Optional[str] = None, ack: Optional[bool] = None, limit: int = 100):
    q = supabase.table("sentinel_alerts").select("*").eq("user_id", user["id"])
    if severity:
        q = q.eq("severity", severity)
    if ack is not None:
        q = q.eq("is_acknowledged", ack)
    q = q.order("created_at", desc=True).limit(limit)
    return q.execute().data or []


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, user=Depends(get_current_user)):
    now = datetime.utcnow().isoformat()
    supabase.table("sentinel_alerts").update({"is_acknowledged": True, "acknowledged_at": now}).eq("id", alert_id).eq("user_id", user["id"]).execute()
    return {"ok": True}


@router.post("/alerts/ack-all")
async def ack_all(user=Depends(get_current_user)):
    now = datetime.utcnow().isoformat()
    supabase.table("sentinel_alerts").update({"is_acknowledged": True, "acknowledged_at": now}).eq("user_id", user["id"]).eq("is_acknowledged", False).execute()
    return {"ok": True}


# ========== SCAN ==========
async def _scan_one(item: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Scan une entree de la watchlist et genere les alertes."""
    siren = item["siren"]
    started = time.time()
    run = supabase.table("sentinel_scan_runs").insert({"watchlist_id": item["id"], "status": "running"}).execute()
    run_id = run.data[0]["id"] if run.data else None
    
    alerts_to_create = []
    signals_checked = 0
    
    try:
        # 1. Recuperer fiche entreprise actuelle
        entreprise = await fetch_entreprise(siren)
        signals_checked += 1
        new_snap = snapshot_signature(entreprise)
        old_snap = item.get("last_snapshot") or {}
        
        # 2. Calculer diff et generer alertes pour les changements
        if item.get("watch_dirigeants") or item.get("watch_capital") or item.get("watch_procedures"):
            diffs = diff_snapshots(old_snap, new_snap)
            alerts_to_create.extend(diffs)
            signals_checked += len(diffs)
        
        # 3. Scan BODACC (dernier 30 jours)
        if item.get("watch_bodacc") or item.get("watch_procedures"):
            annonces = await fetch_bodacc_recent(siren, days=14)
            signals_checked += len(annonces)
            # Filtrer celles dejà alertees (par hash date+type)
            existing_alerts = supabase.table("sentinel_alerts").select("details").eq("watchlist_id", item["id"]).eq("source", "BODACC").execute()
            seen_dates = set()
            for ex in (existing_alerts.data or []):
                if ex.get("details") and ex["details"].get("date_parution"):
                    seen_dates.add(str(ex["details"]["date_parution"]) + (ex["details"].get("raw") or {}).get("typeavis", ""))
            new_alerts = bodacc_to_alerts(annonces)
            for al in new_alerts:
                key = str(al["details"].get("date_parution")) + (al["details"].get("raw") or {}).get("typeavis", "")
                if key not in seen_dates:
                    alerts_to_create.append(al)
        
        # 4. Persister les alertes
        for al in alerts_to_create:
            supabase.table("sentinel_alerts").insert({
                "watchlist_id": item["id"],
                "user_id": user_id,
                "severity": al.get("severity", "info"),
                "category": al.get("category"),
                "title": al.get("title"),
                "description": al.get("description"),
                "details": al.get("details"),
                "source": al.get("source"),
            }).execute()
        
        # 5. Mise a jour du snapshot
        _update = {
            "last_snapshot": new_snap,
            "last_scan_at": datetime.utcnow().isoformat(),
        }
        if (not item.get("raison_sociale") or item.get("raison_sociale") == item["siren"]) and new_snap.get("nom_complet"):
            _update["raison_sociale"] = new_snap.get("nom_complet")
        supabase.table("sentinel_watchlist").update(_update).eq("id", item["id"]).execute()
        
        # 6. Finir le run
        duration_ms = int((time.time() - started) * 1000)
        if run_id:
            supabase.table("sentinel_scan_runs").update({
                "status": "success",
                "finished_at": datetime.utcnow().isoformat(),
                "signals_checked": signals_checked,
                "alerts_generated": len(alerts_to_create),
                "duration_ms": duration_ms,
            }).eq("id", run_id).execute()
        
        return {"siren": siren, "alerts": len(alerts_to_create), "signals": signals_checked, "duration_ms": duration_ms}
    
    except Exception as e:
        if run_id:
            supabase.table("sentinel_scan_runs").update({
                "status": "error",
                "finished_at": datetime.utcnow().isoformat(),
                "error_message": str(e)[:500],
                "duration_ms": int((time.time() - started) * 1000),
            }).eq("id", run_id).execute()
        return {"siren": siren, "error": str(e)}


@router.post("/scan/{watchlist_id}")
async def scan_one(watchlist_id: str, user=Depends(get_current_user)):
    """Scan manuel d'une entree."""
    res = supabase.table("sentinel_watchlist").select("*").eq("id", watchlist_id).eq("user_id", user["id"]).execute()
    if not res.data:
        raise HTTPException(404, "Entree introuvable")
    return await _scan_one_enhanced(res.data[0], user["id"])


@router.post("/scan-all")
async def scan_all(background: BackgroundTasks, user=Depends(get_current_user)):
    """Lance un scan complet de la watchlist (en background)."""
    res = supabase.table("sentinel_watchlist").select("*").eq("user_id", user["id"]).eq("is_active", True).execute()
    items = res.data or []
    
    async def run_all():
        for it in items:
            try:
                await _scan_one_enhanced(it, user["id"])
            except Exception:
                pass
    
    background.add_task(run_all)
    return {"started": True, "count": len(items)}


# ========== STATS / DASHBOARD ==========
@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    w = supabase.table("sentinel_watchlist").select("id,is_active").eq("user_id", user["id"]).execute()
    a = supabase.table("sentinel_alerts").select("severity,is_acknowledged,created_at").eq("user_id", user["id"]).execute()
    items = w.data or []
    alerts = a.data or []
    open_alerts = [x for x in alerts if not x.get("is_acknowledged")]
    today = datetime.utcnow().date().isoformat()
    return {
        "total_entities": len([i for i in items if i.get("is_active")]),
        "total_inactive": len([i for i in items if not i.get("is_active")]),
        "alerts_open": len(open_alerts),
        "alerts_critical": sum(1 for x in open_alerts if x.get("severity") == "critical"),
        "alerts_warning": sum(1 for x in open_alerts if x.get("severity") == "warning"),
        "alerts_today": sum(1 for x in alerts if x.get("created_at", "")[:10] == today),
        "alerts_total_30d": sum(1 for x in alerts if x.get("created_at", "")[:10] >= (datetime.utcnow().date() - timedelta(days=30)).isoformat()),
    }


# ========== BRIEFING ==========
@router.get("/briefing")
async def generate_briefing(user=Depends(get_current_user), days: int = 7):
    """Genere un briefing synthese sur la derniere periode."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    a = supabase.table("sentinel_alerts").select("*").eq("user_id", user["id"]).gte("created_at", since).order("created_at", desc=True).execute()
    alerts = a.data or []
    w = supabase.table("sentinel_watchlist").select("*").eq("user_id", user["id"]).eq("is_active", True).execute()
    entities = w.data or []
    # Joindre nom entreprise sur chaque alerte
    siren_by_id = {e["id"]: {"siren": e["siren"], "raison_sociale": e.get("raison_sociale", "")} for e in entities}
    by_severity = {"critical": [], "warning": [], "info": []}
    for al in alerts:
        sev = al.get("severity", "info")
        ent = siren_by_id.get(al.get("watchlist_id"), {})
        al["_entity"] = ent
        by_severity.setdefault(sev, []).append(al)
    return {
        "period_days": days,
        "generated_at": datetime.utcnow().isoformat(),
        "total_entities": len(entities),
        "total_alerts": len(alerts),
        "critical": by_severity["critical"],
        "warning": by_severity["warning"],
        "info": by_severity["info"][:20],  # limite info
    }


# ========== LINKS / GRAPHE D'INTERETS ==========
@router.post("/links/detect")
async def detect_links(user=Depends(get_current_user)):
    """Croise toutes les entites surveillees pour detecter dirigeants/RBE communs."""
    res = supabase.table("sentinel_watchlist").select("*").eq("user_id", user["id"]).eq("is_active", True).execute()
    items = res.data or []
    links_created = 0
    
    # Pour chaque paire, comparer les dirigeants des snapshots
    for i, a in enumerate(items):
        for b in items[i+1:]:
            snap_a = a.get("last_snapshot") or {}
            snap_b = b.get("last_snapshot") or {}
            dirs_a = set(snap_a.get("dirigeants_noms") or [])
            dirs_b = set(snap_b.get("dirigeants_noms") or [])
            common = dirs_a & dirs_b
            if common:
                # Inserer ou ignorer (UNIQUE constraint)
                try:
                    supabase.table("sentinel_links").insert({
                        "user_id": user["id"],
                        "entity_a_siren": a["siren"],
                        "entity_b_siren": b["siren"],
                        "link_type": "dirigeant_commun",
                        "link_strength": len(common),
                        "details": {"dirigeants_communs": list(common)},
                    }).execute()
                    links_created += 1
                except Exception:
                    pass
    return {"links_created": links_created, "entities_compared": len(items)}


@router.get("/links")
async def list_links(user=Depends(get_current_user)):
    res = supabase.table("sentinel_links").select("*").eq("user_id", user["id"]).order("link_strength", desc=True).execute()
    return res.data or []


# ============================================
# NOTIFICATIONS (Brevo email + webhook tiers)
# ============================================

async def get_user_settings(user_id: str) -> Dict[str, Any]:
    r = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
    return r.data[0] if r.data else {}


async def get_email_settings(user_id: str) -> Dict[str, Any]:
    """Recupere config Brevo de l'utilisateur."""
    try:
        r = supabase.table("email_settings").select("*").eq("user_id", user_id).execute()
        return r.data[0] if r.data else {}
    except Exception:
        return {}


async def send_critical_alert_email(user_id: str, watchlist_entry: Dict[str, Any], alert: Dict[str, Any]):
    """Envoi email Brevo si alerte critique."""
    try:
        email_cfg = await get_email_settings(user_id)
        brevo_key = (email_cfg or {}).get("brevo_api_key")
        if not brevo_key:
            return False
        # Trouver email destinataire
        recipient = watchlist_entry.get("notify_email_address")
        if not recipient:
            u = supabase.table("users").select("email").eq("id", user_id).execute()
            recipient = u.data[0]["email"] if u.data else None
        if not recipient:
            return False
        
        sender_name = (email_cfg or {}).get("sender_name") or "Lexarys Sentinel"
        sender_email = (email_cfg or {}).get("sender_email") or "noreply@lexarys.fr"
        
        rs = watchlist_entry.get("raison_sociale") or watchlist_entry.get("siren")
        subject = f"[Sentinel CRITICAL] {alert.get('title','Alerte')} - {rs}"
        body_html = f"""<!DOCTYPE html><html><body style="font-family:Arial;background:#f1f5f9;padding:20px">
<div style="max-width:600px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)">
  <div style="background:linear-gradient(135deg,#0a1628 0%,#1e293b 100%);color:#fff;padding:24px">
    <div style="color:#d4af37;font-weight:700;letter-spacing:2px;font-size:12px">LEXARYS SENTINEL</div>
    <h1 style="margin:8px 0 0;color:#fff;font-size:22px">Alerte critique detectee</h1>
  </div>
  <div style="padding:24px;color:#0f172a">
    <div style="background:#fee2e2;border-left:4px solid #dc2626;padding:14px;border-radius:6px;margin-bottom:18px">
      <div style="color:#991b1b;font-weight:700;font-size:16px">{alert.get('title','')}</div>
      <div style="color:#7f1d1d;margin-top:6px;font-size:14px">{alert.get('description','')}</div>
    </div>
    <table style="width:100%;font-size:14px;color:#334155;margin-bottom:18px">
      <tr><td style="padding:6px 0;color:#64748b">Entreprise</td><td style="padding:6px 0;color:#0f172a;font-weight:600">{rs}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b">SIREN</td><td style="padding:6px 0;color:#0f172a">{watchlist_entry.get('siren','')}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b">Categorie</td><td style="padding:6px 0;color:#0f172a">{alert.get('category','')}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b">Source</td><td style="padding:6px 0;color:#0f172a">{alert.get('source','')}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b">Detecte le</td><td style="padding:6px 0;color:#0f172a">{datetime.utcnow().strftime('%d/%m/%Y a %H:%M UTC')}</td></tr>
    </table>
    <p style="color:#475569;font-size:13px;line-height:1.6">Connectez-vous a Lexarys Sentinel pour examiner cette alerte et acquitter l'evenement.</p>
    <p style="color:#94a3b8;font-size:11px;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:14px">Cet email est envoye automatiquement par Lexarys Sentinel. Conformite RIN Art. 4 - tracabilite complete.</p>
  </div>
</div></body></html>"""
        
        async with httpx.AsyncClient(timeout=10.0) as cx:
            r = await cx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": brevo_key, "Content-Type": "application/json", "Accept": "application/json"},
                json={
                    "sender": {"name": sender_name, "email": sender_email},
                    "to": [{"email": recipient}],
                    "subject": subject,
                    "htmlContent": body_html,
                }
            )
            return r.status_code in (200, 201, 202)
    except Exception:
        return False


async def fire_webhook(webhook_url: str, payload: Dict[str, Any]):
    if not webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as cx:
            r = await cx.post(webhook_url, json=payload, headers={"User-Agent": "LexarysSentinel/1.0"})
            return r.status_code < 400
    except Exception:
        return False


# ============================================
# DECP (marches publics)
# ============================================

DECP_API = "https://decp.info/api"


async def fetch_decp_recent(siren: str, days: int = 60) -> List[Dict[str, Any]]:
    """Recupere les marches publics gagnes recemment par cette entreprise."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as cx:
            r = await cx.get(f"{DECP_API}/marches/by-titulaire/{siren}", params={"limit": 20})
            if r.status_code != 200:
                return []
            data = r.json()
            marches = data.get("marches", data if isinstance(data, list) else [])
            cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
            return [m for m in marches if (m.get("dateNotification") or m.get("datePublicationDonnees") or "0000") >= cutoff]
    except Exception:
        return []


def decp_to_alerts(marches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    alerts = []
    for m in marches:
        montant = m.get("montant") or m.get("valeur")
        objet = m.get("objet", "")[:200]
        acheteur = (m.get("acheteur") or {}).get("nom") or m.get("acheteurNom", "")
        sev = "info"
        if montant:
            try:
                v = float(montant)
                if v >= 500000:
                    sev = "warning"
                if v >= 5000000:
                    sev = "critical"
            except Exception:
                pass
        alerts.append({
            "category": "marche_public",
            "severity": sev,
            "title": f"Marche public attribue : {objet[:80]}",
            "description": f"Acheteur public : {acheteur} | Montant : {montant or 'non communique'}",
            "source": "DECP",
            "details": {"objet": objet, "acheteur": acheteur, "montant": montant, "date": m.get("dateNotification"), "raw": m},
        })
    return alerts


# ============================================
# CRON ENDPOINT (declenche par cron-job.org ou Railway cron)
# ============================================

@router.post("/cron-scan")
async def cron_scan(background: BackgroundTasks, token: str = ""):
    """Endpoint pour cron externe : declenche un scan de toutes les watchlists actives.
    Requis : token = settings.cron_secret de l'utilisateur."""
    if not token:
        raise HTTPException(401, "Token manquant")
    # Identifier l'utilisateur via le token
    su = supabase.table("user_settings").select("user_id").eq("cron_secret", token).execute()
    if not su.data:
        raise HTTPException(403, "Token invalide")
    user_id = su.data[0]["user_id"]
    
    res = supabase.table("sentinel_watchlist").select("*").eq("user_id", user_id).eq("is_active", True).execute()
    items = res.data or []
    
    async def run_all():
        for it in items:
            try:
                await _scan_one_enhanced(it, user_id)
            except Exception:
                pass
    
    background.add_task(run_all)
    return {"started": True, "count": len(items), "user_id": user_id}


# ============================================
# SCAN ENHANCED (avec DECP + notifications)
# ============================================

async def _scan_one_enhanced(item: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Scan enrichi : entreprise + BODACC + DECP + notifications."""
    base_result = await _scan_one(item, user_id)
    
    # DECP marches publics (si configure)
    if item.get("watch_marches_publics"):
        last_check = item.get("last_decp_check")
        days = 60 if not last_check else max(7, (datetime.utcnow() - datetime.fromisoformat(last_check.replace("Z", "+00:00").split(".")[0]+"+00:00")).days)
        marches = await fetch_decp_recent(item["siren"], days=days)
        new_alerts = decp_to_alerts(marches)
        # Filtrer dejà alertes
        existing = supabase.table("sentinel_alerts").select("details").eq("watchlist_id", item["id"]).eq("source", "DECP").execute()
        seen = set()
        for ex in (existing.data or []):
            d = ex.get("details") or {}
            seen.add(str(d.get("date")) + str(d.get("objet"))[:40])
        for al in new_alerts:
            key = str(al["details"].get("date")) + str(al["details"].get("objet"))[:40]
            if key not in seen:
                ins = supabase.table("sentinel_alerts").insert({
                    "watchlist_id": item["id"], "user_id": user_id,
                    "severity": al["severity"], "category": al["category"],
                    "title": al["title"], "description": al["description"],
                    "details": al["details"], "source": al["source"],
                }).execute()
                # Notify si critique
                if al["severity"] == "critical":
                    await send_critical_alert_email(user_id, item, al)
                    if item.get("webhook_url"):
                        await fire_webhook(item["webhook_url"], {"event": "critical_alert", "alert": al, "entity": {"siren": item["siren"], "raison_sociale": item.get("raison_sociale")}})
        supabase.table("sentinel_watchlist").update({"last_decp_check": datetime.utcnow().isoformat()}).eq("id", item["id"]).execute()
    
    # Pour les alertes critiques deja generees par _scan_one
    # Verifier les recentes (last 60s) critiques et notifier
    if base_result.get("alerts", 0) > 0:
        recent_crit = supabase.table("sentinel_alerts").select("*").eq("watchlist_id", item["id"]).eq("severity", "critical").gte("created_at", (datetime.utcnow() - timedelta(minutes=2)).isoformat()).eq("notified_email", False).execute()
        for al in (recent_crit.data or []):
            ok = await send_critical_alert_email(user_id, item, al)
            if ok:
                supabase.table("sentinel_alerts").update({"notified_email": True}).eq("id", al["id"]).execute()
            if item.get("webhook_url"):
                await fire_webhook(item["webhook_url"], {"event": "critical_alert", "alert": al, "entity": {"siren": item["siren"], "raison_sociale": item.get("raison_sociale")}})
    
    return base_result


@router.post("/scan-enhanced/{watchlist_id}")
async def scan_one_enhanced(watchlist_id: str, user=Depends(get_current_user)):
    res = supabase.table("sentinel_watchlist").select("*").eq("id", watchlist_id).eq("user_id", user["id"]).execute()
    if not res.data:
        raise HTTPException(404)
    return await _scan_one_enhanced(res.data[0], user["id"])


# ============================================
# USER SETTINGS (cron secret, cabinet header)
# ============================================

class UserSettingsUpdate(BaseModel):
    cabinet_name: Optional[str] = None
    cabinet_address: Optional[str] = None
    cabinet_barreau: Optional[str] = None
    cabinet_phone: Optional[str] = None
    cabinet_email: Optional[str] = None
    cabinet_logo_url: Optional[str] = None
    briefing_frequency: Optional[str] = None
    briefing_recipients: Optional[List[str]] = None


@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    s = await get_user_settings(user["id"])
    if not s:
        # Cree au vol avec un secret
        import secrets
        secret = secrets.token_hex(16)
        supabase.table("user_settings").insert({"user_id": user["id"], "cron_secret": secret}).execute()
        s = {"user_id": user["id"], "cron_secret": secret}
    return s


@router.put("/settings")
async def update_settings(body: UserSettingsUpdate, user=Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    data["updated_at"] = datetime.utcnow().isoformat()
    res = supabase.table("user_settings").update(data).eq("user_id", user["id"]).execute()
    return res.data[0] if res.data else {}


@router.post("/settings/regenerate-secret")
async def regen_secret(user=Depends(get_current_user)):
    import secrets
    new = secrets.token_hex(16)
    supabase.table("user_settings").update({"cron_secret": new, "updated_at": datetime.utcnow().isoformat()}).eq("user_id", user["id"]).execute()
    return {"cron_secret": new}


# ============================================
# BRIEFING HTML/PDF
# ============================================

@router.get("/briefing-html")
async def briefing_html(days: int = 7, user=Depends(get_current_user)):
    """Genere une page HTML print-ready pour briefing executive."""
    from fastapi.responses import HTMLResponse
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    a = supabase.table("sentinel_alerts").select("*").eq("user_id", user["id"]).gte("created_at", since).order("created_at", desc=True).execute()
    alerts = a.data or []
    w = supabase.table("sentinel_watchlist").select("*").eq("user_id", user["id"]).eq("is_active", True).execute()
    entities = w.data or []
    settings = await get_user_settings(user["id"]) or {}
    
    siren_by_id = {e["id"]: e for e in entities}
    by_severity = {"critical": [], "warning": [], "info": []}
    for al in alerts:
        sev = al.get("severity", "info")
        ent = siren_by_id.get(al.get("watchlist_id"), {})
        al["_entity"] = ent
        by_severity.setdefault(sev, []).append(al)
    
    cabinet = settings.get("cabinet_name") or "Cabinet"
    barreau = settings.get("cabinet_barreau") or ""
    address = settings.get("cabinet_address") or ""
    phone = settings.get("cabinet_phone") or ""
    email = settings.get("cabinet_email") or ""
    
    def section(items, color, label):
        if not items:
            return ""
        rows = "".join([
            f"<tr><td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;width:160px;color:#475569'>{a.get('_entity',{}).get('raison_sociale') or a.get('_entity',{}).get('siren','')}</td><td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;color:#0f172a'><strong>{a.get('title','')}</strong><br><small style='color:#64748b'>{a.get('description','')[:300]}</small></td><td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;color:#64748b;font-size:12px;text-align:right;width:120px'>{a.get('created_at','')[:10]}<br><span style='color:#94a3b8'>{a.get('source','')}</span></td></tr>"
            for a in items
        ])
        return f"""<h2 style="color:{color};margin:24px 0 8px;font-size:18px;border-bottom:2px solid {color};padding-bottom:6px">{label} ({len(items)})</h2>
<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff">
<thead><tr style="background:#f8fafc"><th style="text-align:left;padding:8px 12px;color:#475569;font-size:11px;text-transform:uppercase">Entite</th><th style="text-align:left;padding:8px 12px;color:#475569;font-size:11px;text-transform:uppercase">Evenement</th><th style="text-align:right;padding:8px 12px;color:#475569;font-size:11px;text-transform:uppercase">Date / Source</th></tr></thead>
<tbody>{rows}</tbody></table>"""
    
    body = section(by_severity["critical"], "#dc2626", "Alertes critiques") + section(by_severity["warning"], "#b45309", "Avertissements") + section(by_severity["info"][:30], "#1e40af", "Informations")
    if not body:
        body = '<div style="text-align:center;padding:60px;color:#64748b;background:#f1f5f9;border-radius:12px">Aucun evenement detecte sur la periode.</div>'
    
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Briefing Sentinel</title>
<style>
@page{{margin:1.5cm;size:A4}}
body{{font-family:'Helvetica',Arial,sans-serif;color:#0f172a;margin:0;padding:20px;background:#fff;line-height:1.5}}
.header{{border-bottom:3px solid #d4af37;padding-bottom:16px;margin-bottom:24px}}
.cabinet{{color:#0a1628;font-size:22px;font-weight:700;margin-bottom:4px}}
.cabinet-meta{{color:#475569;font-size:13px}}
.title{{color:#d4af37;letter-spacing:3px;font-size:11px;font-weight:700;margin-top:10px}}
.summary{{background:#0a1628;color:#f8fafc;padding:20px;border-radius:10px;margin-bottom:24px;display:flex;justify-content:space-around;text-align:center}}
.summary div{{flex:1}}
.summary .big{{font-size:32px;font-weight:800;color:#d4af37}}
.summary .lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;margin-top:4px}}
.footer{{margin-top:40px;padding-top:14px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:10px;text-align:center}}
.print-btn{{position:fixed;top:10px;right:10px;background:#d4af37;color:#0a1628;border:none;padding:10px 16px;border-radius:8px;font-weight:700;cursor:pointer;font-size:13px}}
@media print{{.print-btn{{display:none}}}}
</style></head>
<body>
<button class="print-btn" onclick="window.print()">Imprimer / Exporter PDF</button>
<div class="header">
  <div class="cabinet">{cabinet}</div>
  <div class="cabinet-meta">{barreau}{' - ' if barreau and address else ''}{address}</div>
  <div class="cabinet-meta">{phone}{' - ' if phone and email else ''}{email}</div>
  <div class="title">LEXARYS SENTINEL - BRIEFING DE VEILLE</div>
</div>
<div style="color:#475569;font-size:13px;margin-bottom:18px">
Periode : {(datetime.utcnow() - timedelta(days=days)).strftime('%d/%m/%Y')} - {datetime.utcnow().strftime('%d/%m/%Y')} ({days} jours)<br>
Genere le {datetime.utcnow().strftime('%d/%m/%Y a %H:%M UTC')}
</div>
<div class="summary">
  <div><div class="big">{len(entities)}</div><div class="lbl">Entites surveillees</div></div>
  <div><div class="big">{len(alerts)}</div><div class="lbl">Evenements detectes</div></div>
  <div><div class="big" style="color:#fca5a5">{len(by_severity['critical'])}</div><div class="lbl">Critiques</div></div>
  <div><div class="big" style="color:#fcd34d">{len(by_severity['warning'])}</div><div class="lbl">Avertissements</div></div>
</div>
{body}
<div class="footer">Document confidentiel - Cabinet {cabinet} - Genere par Lexarys Sentinel - Conformite RIN Art. 4</div>
</body></html>"""
    return HTMLResponse(html)


# ============================================
# ===== OPPORTUNITIES (recherche prospection)
# ============================================

class OpportunitySearch(BaseModel):
    event_type: str = "all"  # all | procedure_collective | creation_recente | marche_public | modification_capital | changement_dirigeant
    departement: Optional[str] = None  # "75", "69", etc.
    activite_naf: Optional[str] = None  # code NAF style "68.31Z"
    effectif_min: Optional[int] = None
    effectif_max: Optional[int] = None
    days_back: int = 30
    limit: int = 50


async def search_bodacc_opportunities(filter_type: str, dept: Optional[str], days: int, limit: int) -> List[Dict[str, Any]]:
    """Recupere annonces BODACC selon le type d'evenement (opportunites)."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "dataset": "annonces-commerciales",
        "rows": min(limit, 100),
        "sort": "-dateparution",
        "refine.dateparution": ">=" + since,
    }
    if filter_type == "procedure_collective":
        params["q"] = "redressement OR liquidation OR sauvegarde"
    elif filter_type == "modification_capital":
        params["refine.familleavis"] = "modification"
    elif filter_type == "cession":
        params["q"] = "vente OR cession"
    if dept:
        params["refine.departement_nom_officiel"] = dept
    async with httpx.AsyncClient(timeout=15.0) as cx:
        try:
            r = await cx.get(BODACC_API, params=params)
            if r.status_code != 200:
                return []
            records = r.json().get("records", [])
            results = []
            for rec in records:
                f = rec.get("fields", {})
                # Extraire SIREN
                listep = f.get("listepersonnes", "")
                # tenter d'extraire SIREN depuis le texte
                siren_match = re.search(r"(\d{9})", listep + " " + (f.get("publicationavis_facette") or ""))
                siren = siren_match.group(1) if siren_match else None
                if not siren:
                    continue
                results.append({
                    "siren": siren,
                    "raison_sociale": (listep[:200] if listep else ""),
                    "event_type": filter_type,
                    "event_title": f.get("typeavis", ""),
                    "event_description": f.get("publicationavis_facette", "")[:300],
                    "date_event": f.get("dateparution"),
                    "departement": f.get("departement_nom_officiel"),
                    "tribunal": f.get("tribunal"),
                    "source": "BODACC",
                    "score_potentiel": 70 if filter_type == "procedure_collective" else 50,
                })
            # Deduplication par SIREN
            seen = set()
            unique = []
            for r in results:
                if r["siren"] not in seen:
                    seen.add(r["siren"])
                    unique.append(r)
            return unique[:limit]
        except Exception:
            return []


async def search_recent_creations(dept: Optional[str], naf: Optional[str], eff_min: Optional[int], eff_max: Optional[int], days: int, limit: int) -> List[Dict[str, Any]]:
    """Recherche les entreprises creees recemment via recherche-entreprises.api.gouv.fr"""
    params = {
        "per_page": min(limit, 25),
        "page": 1,
    }
    # date_creation_min n'est pas un parametre standard, on filtrera apres
    if dept:
        params["code_postal"] = dept + "*"
    if naf:
        params["activite_principale"] = naf
    if eff_min is not None or eff_max is not None:
        # tranches: 00 (0 sal), 01 (1-2), 02 (3-5), 03 (6-9), 11 (10-19), 12 (20-49), 21 (50-99), 22 (100-199), 31 (200-249), 32 (250-499), 41 (500-999), 42 (1000-1999), 51 (2000-4999), 52 (5000-9999), 53 (10000+)
        trs = []
        eff_mapping = [(0,0,"00"),(1,2,"01"),(3,5,"02"),(6,9,"03"),(10,19,"11"),(20,49,"12"),(50,99,"21"),(100,199,"22"),(200,249,"31"),(250,499,"32"),(500,999,"41"),(1000,1999,"42"),(2000,4999,"51"),(5000,9999,"52"),(10000,99999999,"53")]
        for mn, mx, code in eff_mapping:
            if (eff_min is None or mx >= eff_min) and (eff_max is None or mn <= eff_max):
                trs.append(code)
        if trs:
            params["tranche_effectif_salarie"] = ",".join(trs)
    
    # On veut les plus recentes
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    async with httpx.AsyncClient(timeout=15.0) as cx:
        try:
            r = await cx.get(API_GOUV, params=params)
            if r.status_code != 200:
                return []
            results = r.json().get("results", [])
            out = []
            for ent in results:
                date_c = ent.get("date_creation")
                if date_c and date_c < cutoff:
                    continue
                siren = ent.get("siren")
                if not siren:
                    continue
                siege = ent.get("siege") or {}
                dirs = ent.get("dirigeants") or []
                # Score preliminaire
                score = 50
                if ent.get("nombre_etablissements_ouverts") and ent["nombre_etablissements_ouverts"] > 1:
                    score += 10
                if dirs:
                    score += 5
                if (ent.get("tranche_effectif_salarie") or "00") not in ("NN", "00"):
                    score += 10
                out.append({
                    "siren": siren,
                    "raison_sociale": ent.get("nom_complet") or ent.get("nom_raison_sociale", ""),
                    "event_type": "creation_recente",
                    "event_title": "Creation recente",
                    "event_description": f"Cree le {date_c} - {ent.get('activite_principale','')}",
                    "date_event": date_c,
                    "ville": siege.get("libelle_commune"),
                    "adresse": siege.get("adresse"),
                    "code_postal": siege.get("code_postal"),
                    "departement": (siege.get("code_postal") or "")[:2] if siege.get("code_postal") else None,
                    "dirigeants_count": len(dirs),
                    "activite": ent.get("activite_principale"),
                    "tranche_effectif": ent.get("tranche_effectif_salarie"),
                    "source": "Recherche-Entreprises",
                    "score_potentiel": min(95, score),
                })
            return out[:limit]
        except Exception:
            return []


async def search_marches_publics_recent(dept: Optional[str], days: int, limit: int) -> List[Dict[str, Any]]:
    """Recherche les marches publics attribues recemment."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as cx:
            params = {"limit": min(limit, 50)}
            if dept:
                params["dept"] = dept
            r = await cx.get(f"{DECP_API}/marches/recent", params=params)
            if r.status_code != 200:
                return []
            data = r.json()
            marches = data if isinstance(data, list) else data.get("marches", [])
            cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
            out = []
            for m in marches:
                date_n = m.get("dateNotification") or m.get("datePublicationDonnees")
                if date_n and date_n < cutoff:
                    continue
                titulaires = m.get("titulaires") or []
                for t in titulaires:
                    siren = (t.get("id") or "")[:9]
                    if not siren or not siren.isdigit():
                        continue
                    montant = m.get("montant") or 0
                    try:
                        montant = float(montant)
                    except Exception:
                        montant = 0
                    score = 60
                    if montant >= 500000:
                        score = 75
                    if montant >= 5000000:
                        score = 85
                    out.append({
                        "siren": siren,
                        "raison_sociale": t.get("denominationSociale") or t.get("nom", ""),
                        "event_type": "marche_public",
                        "event_title": f"Marche public attribue ({int(montant)} EUR)" if montant else "Marche public attribue",
                        "event_description": (m.get("objet", "") or "")[:300],
                        "date_event": date_n,
                        "departement": dept,
                        "acheteur": (m.get("acheteur") or {}).get("nom") or m.get("acheteurNom", ""),
                        "montant": montant,
                        "source": "DECP",
                        "score_potentiel": score,
                    })
            return out[:limit]
    except Exception:
        return []


@router.post("/opportunities")
async def search_opportunities(body: OpportunitySearch, user=Depends(get_current_user)):
    """Recherche d'opportunites commerciales basee sur des evenements recents."""
    results = []
    event_type = body.event_type
    
    if event_type in ("all", "procedure_collective"):
        try:
            r1 = await search_bodacc_opportunities("procedure_collective", body.departement, body.days_back, body.limit)
            results.extend(r1)
        except Exception:
            pass
    
    if event_type in ("all", "modification_capital"):
        try:
            r2 = await search_bodacc_opportunities("modification_capital", body.departement, body.days_back, body.limit // 2 if event_type == "all" else body.limit)
            results.extend(r2)
        except Exception:
            pass
    
    if event_type in ("all", "creation_recente"):
        try:
            r3 = await search_recent_creations(body.departement, body.activite_naf, body.effectif_min, body.effectif_max, body.days_back, body.limit // 2 if event_type == "all" else body.limit)
            results.extend(r3)
        except Exception:
            pass
    
    if event_type in ("all", "marche_public"):
        try:
            r4 = await search_marches_publics_recent(body.departement, body.days_back, body.limit // 2 if event_type == "all" else body.limit)
            results.extend(r4)
        except Exception:
            pass
    
    # Croiser avec prospects/clients existants pour exclure ceux deja en base
    try:
        existing_prospects = supabase.table("prospects").select("siren").eq("user_id", user["id"]).execute()
        existing_sirens = set([p.get("siren") for p in (existing_prospects.data or []) if p.get("siren")])
        existing_clients = supabase.table("clients").select("siren").eq("user_id", user["id"]).execute()
        for c in (existing_clients.data or []):
            if c.get("siren"):
                existing_sirens.add(c["siren"])
        existing_watch = supabase.table("sentinel_watchlist").select("siren").eq("user_id", user["id"]).execute()
        watched_sirens = set([w.get("siren") for w in (existing_watch.data or []) if w.get("siren")])
        
        for r in results:
            r["already_prospect"] = r.get("siren") in existing_sirens
            r["already_watched"] = r.get("siren") in watched_sirens
    except Exception:
        pass
    
    # Trier par score_potentiel desc, dedupliquer
    seen = set()
    unique = []
    for r in sorted(results, key=lambda x: -(x.get("score_potentiel") or 0)):
        if r["siren"] not in seen:
            seen.add(r["siren"])
            unique.append(r)
    
    return {"count": len(unique), "results": unique[:body.limit]}


@router.post("/opportunities/convert-to-prospect")
async def convert_to_prospect(body: Dict[str, Any], user=Depends(get_current_user)):
    """Convertit une opportunite en prospect."""
    siren = body.get("siren")
    if not siren:
        raise HTTPException(400, "SIREN manquant")
    # Verifier non-existence
    existing = supabase.table("prospects").select("id").eq("user_id", user["id"]).eq("siren", siren).execute()
    if existing.data:
        return {"already_exists": True, "prospect_id": existing.data[0]["id"]}
    data = {
        "user_id": user["id"],
        "siren": siren,
        "raison_sociale": body.get("raison_sociale", ""),
        "ville": body.get("ville"),
        "adresse": body.get("adresse"),
        "code_postal": body.get("code_postal"),
        "activite_principale": body.get("activite"),
        "statut": "identifie",
        "priorite": "normal",
        "notes": f"Source: Sentinel Opportunites - {body.get('event_title','')}\n{body.get('event_description','')}",
    }
    try:
        res = supabase.table("prospects").insert(data).execute()
        return {"created": True, "prospect": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(500, f"Erreur creation prospect : {str(e)}")
