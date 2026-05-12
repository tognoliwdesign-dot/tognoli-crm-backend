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
    watch_marches_publics: bool = False
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
        r = await cx.get(API_GOUV, params={"q": siren, "include": "complements,siege,matching_etablissements,dirigeants"})
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
        supabase.table("sentinel_watchlist").update({
            "last_snapshot": new_snap,
            "last_scan_at": datetime.utcnow().isoformat(),
        }).eq("id", item["id"]).execute()
        
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
    return await _scan_one(res.data[0], user["id"])


@router.post("/scan-all")
async def scan_all(background: BackgroundTasks, user=Depends(get_current_user)):
    """Lance un scan complet de la watchlist (en background)."""
    res = supabase.table("sentinel_watchlist").select("*").eq("user_id", user["id"]).eq("is_active", True).execute()
    items = res.data or []
    
    async def run_all():
        for it in items:
            try:
                await _scan_one(it, user["id"])
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
