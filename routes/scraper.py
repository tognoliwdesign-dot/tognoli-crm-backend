"""
LEXARYS — Scraper de prospection (4 piliers)
Conformité RGPD : Art. 6.1.f — registres publics officiels
Conformité RIN : Art. 161

ALGORITHME DE SCORING (4 PILIERS) :
  Pilier 1 — Solvabilité (filtre éliminatoire)
  Pilier 2 — Capacité contributive (tranches TPE/PME/ETI/GC)
  Pilier 3 — Trajectoire (dynamique 24-36 mois)
  Pilier 4 — Déclencheurs juridiques (event-based, par spécialité)
"""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from auth import get_current_user
from services.sirene import search_sirene, get_bodacc, get_pappers
from database import supabase

router = APIRouter(prefix="/scraper", tags=["scraper"])


def _pilier1_solvabilite(bodacc: dict, pappers: dict) -> dict:
    flags = []
    eliminated = False
    color = "vert"
    score_malus = 0

    procedure = bodacc.get("procedure")
    procedure_recent = bodacc.get("procedure_recent", False)

    if procedure == "liquidation":
        eliminated = True
        color = "rouge"
        flags.append({"type": "liquidation", "label": "⛔ Liquidation judiciaire — contact non rentable", "severity": "elimination"})
    elif procedure == "redressement" and procedure_recent:
        color = "rouge"
        score_malus = 20
        flags.append({"type": "redressement_recent", "label": "🚨 Redressement judiciaire récent (< 3 ans)", "severity": "rouge"})
    elif procedure == "sauvegarde" and procedure_recent:
        color = "orange"
        score_malus = 10
        flags.append({"type": "sauvegarde_recente", "label": "⚠️ Procédure de sauvegarde récente", "severity": "orange"})
    elif procedure == "cession":
        color = "orange"
        score_malus = 5
        flags.append({"type": "cession", "label": "⚠️ Cession d'activité — besoins juridiques en cours", "severity": "orange"})

    if pappers.get("available"):
        if pappers.get("equity_alert"):
            if color == "vert": color = "orange"
            score_malus += 15
            flags.append({"type": "equity_alert", "label": "⚠️ Capitaux propres < 50% du capital social (art. L223-42)", "severity": "orange"})
        if pappers.get("accounts_not_filed"):
            if color == "vert": color = "orange"
            score_malus += 10
            yr = pappers.get("last_accounts_year") or 0
            flags.append({"type": "accounts_not_filed", "label": f"⚠️ Comptes non déposés depuis {datetime.now().year - yr} ans", "severity": "orange"})
        resultat = pappers.get("resultat_net_latest")
        if resultat is not None and resultat < 0:
            score_malus += 5
            flags.append({"type": "resultat_negatif", "label": f"⚠️ Résultat net négatif ({_fmt_montant(resultat)}€)", "severity": "warning"})

    return {"color": color, "flags": flags, "eliminated": eliminated, "score_malus": score_malus}


EFFECTIF_TRANCHE = {
    "NN": None, "00": None,
    "01": "TPE", "02": "TPE", "03": "TPE",
    "11": "PME", "12": "PME",
    "21": "PME+", "22": "PME+",
    "31": "ETI", "32": "ETI",
    "41": "GC", "42": "GC",
    "51": "GC", "52": "GC",
}

TRANCHE_CONFIG = {
    "TPE":  {"symbol": "€",     "label": "TPE (1-9 sal.)",     "score": 30, "honoraires": "< 5k€/an"},
    "PME":  {"symbol": "€€",    "label": "PME (10-49 sal.)",   "score": 55, "honoraires": "5-30k€/an"},
    "PME+": {"symbol": "€€€",   "label": "PME+ (50-199 sal.)", "score": 70, "honoraires": "15-80k€/an"},
    "ETI":  {"symbol": "€€€€",  "label": "ETI (200-499 sal.)", "score": 85, "honoraires": "40-200k€/an"},
    "GC":   {"symbol": "€€€€€", "label": "Grand Compte (500+)","score": 90, "honoraires": "> 100k€/an"},
}


def _naf_capacity_bonus(naf_code: str) -> tuple:
    if not naf_code:
        return 0, "", []
    naf = naf_code.replace(".", "").upper()
    p2 = naf[:2]
    p1 = naf[:1]
    if p2 == "69": return -20, "Secteur juridique/comptable — exclure", []
    if p2 in ("41", "42", "43"): return 15, "BTP/Construction — fort besoin juridique", ["contentieux", "commercial", "droit_travail"]
    if p2 == "68": return 12, "Immobilier — besoins contractuels et fiscaux", ["immobilier", "fiscal", "commercial"]
    if p2 in ("64", "65", "66"): return 10, "Finance/Assurance — compliance & contrats", ["fiscal", "commercial", "corporate"]
    if p2 in ("45", "46", "47"): return 12, "Commerce — litiges commerciaux et contrats", ["commercial", "contentieux"]
    if p1 in ("1", "2", "3"): return 10, "Industrie — contrats, HSE, litiges", ["commercial", "droit_travail", "hse"]
    if p2 in ("49", "50", "51", "52", "53"): return 8, "Transport/Logistique — droit des contrats", ["commercial", "contentieux"]
    if p2 in ("58", "59", "60", "61", "62", "63"): return 10, "Tech/Media — PI et contrats", ["propriete_intellectuelle", "commercial", "corporate"]
    if p2 in ("55", "56"): return 5, "HCR — droit du travail", ["droit_travail"]
    if p2 in ("72", "73", "74", "75"): return 8, "R&D/Conseil — contrats IP", ["propriete_intellectuelle", "commercial"]
    if p2 in ("86", "87", "88"): return 5, "Santé — réglementé", ["sante", "droit_travail"]
    if p2 in ("84", "85"): return 3, "Public/Éducation", ["droit_public"]
    return 0, "", []


def _pilier2_capacite(p: dict, pappers: dict) -> dict:
    effectif_code = (p.get("effectif_tranche") or "").strip()
    tranche_key = EFFECTIF_TRANCHE.get(effectif_code)
    tranche = TRANCHE_CONFIG.get(tranche_key or "TPE", TRANCHE_CONFIG["TPE"])
    naf_bonus, naf_label, naf_specialites = _naf_capacity_bonus(p.get("naf_code", ""))
    base_score = tranche["score"] + naf_bonus

    forme = (p.get("forme_juridique") or "").upper()
    forme_bonus = 0
    forme_label = ""
    if any(x in forme for x in ["5505", "5710", "5720", "SA"]):
        forme_bonus = 8; forme_label = "SA/SAS — structure juridique complexe"
    elif any(x in forme for x in ["5498", "SARL", "5485"]):
        forme_bonus = 4; forme_label = "SARL — besoins juridiques standard"
    base_score += forme_bonus

    pappers_label = ""
    if pappers.get("available"):
        ca = pappers.get("ca_latest")
        if ca:
            if ca > 50_000_000: base_score += 10; pappers_label = f"CA : {_fmt_montant(ca)}€"
            elif ca > 10_000_000: base_score += 6; pappers_label = f"CA : {_fmt_montant(ca)}€"
            elif ca > 2_000_000: base_score += 3; pappers_label = f"CA : {_fmt_montant(ca)}€"

    return {
        "tranche": tranche_key or "?",
        "symbol": tranche["symbol"],
        "label": tranche["label"],
        "honoraires": tranche["honoraires"],
        "score": max(0, min(100, base_score)),
        "naf_label": naf_label,
        "naf_specialites": naf_specialites,
        "forme_label": forme_label,
        "pappers_label": pappers_label,
        "ca_latest": pappers.get("ca_latest") if pappers.get("available") else None,
    }


def _pilier3_trajectoire(p: dict, bodacc: dict, pappers: dict) -> dict:
    score = 50
    signals = []
    now = datetime.now()
    age_years = None

    date_creation = p.get("date_creation")
    if date_creation:
        try:
            created = datetime.fromisoformat(str(date_creation)[:10])
            age_years = (now - created).days // 365
            if age_years < 2:
                score -= 15; signals.append({"label": f"Entreprise très récente ({age_years} an(s)) — risque élevé", "kind": "negative"})
            elif age_years <= 5:
                score -= 5; signals.append({"label": f"Entreprise jeune ({age_years} ans)", "kind": "neutral"})
            elif age_years <= 15:
                score += 15; signals.append({"label": f"Entreprise mature ({age_years} ans) — sweet spot", "kind": "positive"})
            elif age_years <= 30:
                score += 8; signals.append({"label": f"Entreprise établie ({age_years} ans)", "kind": "positive"})
            else:
                score += 3; signals.append({"label": f"Entreprise ancienne ({age_years} ans)", "kind": "neutral"})
        except Exception:
            pass

    if pappers.get("available"):
        growth = pappers.get("ca_growth_pct")
        if growth is not None:
            if growth > 30: score += 20; signals.append({"label": f"📈 Croissance CA +{growth}% — forte dynamique", "kind": "positive"})
            elif growth > 10: score += 12; signals.append({"label": f"📈 Croissance CA +{growth}%", "kind": "positive"})
            elif growth > 0: score += 5; signals.append({"label": f"CA stable (+{growth}%)", "kind": "positive"})
            elif growth < -20: score -= 15; signals.append({"label": f"📉 Déclin CA {growth}%", "kind": "negative"})
            elif growth < 0: score -= 5; signals.append({"label": f"📉 CA en légère baisse ({growth}%)", "kind": "negative"})

        resultat = pappers.get("resultat_net_latest")
        ca = pappers.get("ca_latest")
        if resultat is not None and ca and ca > 0:
            marge = resultat / ca * 100
            if marge > 10: score += 10; signals.append({"label": f"✅ Marge nette {marge:.1f}% — bonne santé", "kind": "positive"})
            elif marge > 3: score += 4
            elif marge < 0: score -= 8; signals.append({"label": "⚠️ Résultat net négatif", "kind": "negative"})

    events = bodacc.get("events", [])
    if any(e.get("type") == "modification_statuts" and e.get("recent") for e in events):
        score += 8; signals.append({"label": "🔄 Modification statutaire récente", "kind": "positive"})
    if bodacc.get("has_recent_creation"):
        score += 5; signals.append({"label": "🆕 Création/immatriculation récente", "kind": "positive"})
    if bodacc.get("has_dissolution"):
        score -= 20; signals.append({"label": "⛔ Procédure de dissolution", "kind": "negative"})

    return {"score": max(0, min(100, score)), "signals": signals, "age_years": age_years, "ca_growth_pct": pappers.get("ca_growth_pct") if pappers.get("available") else None}


def _pilier4_declencheurs(p: dict, bodacc: dict, pappers: dict) -> list:
    triggers = []
    events = bodacc.get("events", [])
    naf = (p.get("naf_code") or "").replace(".", "").upper()
    p2 = naf[:2]

    procedure = bodacc.get("procedure")
    if procedure == "redressement":
        triggers.append({"type": "procedure_collective", "label": "🚨 Redressement judiciaire — besoin avocat URGENT", "source": "BODACC", "date": bodacc.get("procedure_date"), "window": "3 mois", "urgency": "haute", "specialites": ["contentieux", "restructuring", "commercial"], "score_bonus": 25})
    elif procedure == "sauvegarde":
        triggers.append({"type": "procedure_collective", "label": "⚡ Procédure de sauvegarde — intervention recommandée", "source": "BODACC", "date": bodacc.get("procedure_date"), "window": "6 mois", "urgency": "haute", "specialites": ["contentieux", "restructuring"], "score_bonus": 20})
    elif procedure == "cession":
        triggers.append({"type": "cession_activite", "label": "Cession d'activité — besoins M&A", "source": "BODACC", "date": bodacc.get("procedure_date"), "window": "6 mois", "urgency": "moyenne", "specialites": ["corporate", "fiscal", "commercial"], "score_bonus": 15})

    mods = [e for e in events if e.get("type") == "modification_statuts" and e.get("recent")]
    if mods:
        triggers.append({"type": "modification_statuts", "label": "🔄 Modification statutaire récente", "source": "BODACC", "date": mods[0].get("date"), "window": "6 mois", "urgency": "moyenne", "specialites": ["corporate", "fiscal"], "score_bonus": 10})

    if pappers.get("available"):
        growth = pappers.get("ca_growth_pct")
        if growth and growth > 50:
            triggers.append({"type": "levee_fonds", "label": f"💰 Croissance exceptionnelle ({growth}%/an)", "source": "Pappers", "date": None, "window": "12 mois", "urgency": "haute", "specialites": ["corporate", "fiscal", "ma"], "score_bonus": 20})
        elif growth and growth > 20:
            triggers.append({"type": "croissance_forte", "label": f"📈 Croissance forte ({growth}%/an)", "source": "Pappers", "date": None, "window": "12 mois", "urgency": "moyenne", "specialites": ["droit_travail", "commercial", "corporate"], "score_bonus": 12})
        for d in (pappers.get("dirigeants") or []):
            debut = d.get("date_debut")
            if debut:
                try:
                    debut_date = datetime.fromisoformat(str(debut)[:10])
                    if debut_date > datetime.now() - timedelta(days=365):
                        triggers.append({"type": "changement_dirigeant", "label": f"👤 Nouveau dirigeant ({d.get('nom', '')})", "source": "Pappers", "date": debut, "window": "6 mois", "urgency": "moyenne", "specialites": ["corporate", "droit_travail"], "score_bonus": 8})
                        break
                except Exception:
                    pass

    if p2 in ("86", "87", "88"):
        triggers.append({"type": "secteur_reglemente", "label": "🏥 Santé — obligations permanentes", "source": "Sirene", "date": None, "window": "permanent", "urgency": "faible", "specialites": ["sante", "droit_travail"], "score_bonus": 5})
    elif p2 in ("64", "65", "66"):
        triggers.append({"type": "secteur_reglemente", "label": "🏦 Finance/Assurance — compliance permanente", "source": "Sirene", "date": None, "window": "permanent", "urgency": "faible", "specialites": ["fiscal", "compliance"], "score_bonus": 8})
    elif p2 in ("41", "42", "43"):
        triggers.append({"type": "secteur_btp", "label": "🏗️ BTP — litiges récurrents", "source": "Sirene", "date": None, "window": "permanent", "urgency": "faible", "specialites": ["contentieux", "commercial", "droit_travail"], "score_bonus": 10})
    elif p2 in ("58", "59", "60", "61", "62", "63"):
        triggers.append({"type": "secteur_tech", "label": "💻 Tech/Media — PI, RGPD & contrats", "source": "Sirene", "date": None, "window": "permanent", "urgency": "faible", "specialites": ["propriete_intellectuelle", "commercial"], "score_bonus": 8})

    urgency_order = {"haute": 0, "moyenne": 1, "faible": 2}
    triggers.sort(key=lambda t: urgency_order.get(t["urgency"], 3))
    return triggers


def _score_complet(p: dict, bodacc: dict, pappers: dict, cabinet_entities: list) -> dict:
    name_lower = (p.get("company_name") or "").lower().strip()
    siren = (p.get("siren") or "").strip()
    conflict_malus = 0
    conflict_label = ""

    for entity in cabinet_entities:
        e_name = (entity.get("name") or "").lower().strip()
        e_siren = (entity.get("siren") or "").strip()
        matched = (siren and e_siren and siren == e_siren) or (
            name_lower and e_name and len(name_lower) > 5
            and (name_lower == e_name or name_lower in e_name or e_name in name_lower)
        )
        if matched:
            etype = entity.get("type", "")
            if etype == "client_actuel":
                return {
                    "score": 0, "match_score": 0,
                    "solvabilite": {"color": "rouge", "flags": [{"label": "Client actuel — contact interdit (RIN Art. 4)", "type": "conflict", "severity": "elimination"}], "eliminated": True, "score_malus": 100},
                    "capacite": {}, "trajectoire": {}, "declencheurs": [],
                    "deonto_color": "rouge", "deonto_alert": True,
                    "score_breakdown": {"conflit": "Client actuel — contact interdit (RIN Art. 4)"},
                }
            elif etype == "client_ancien":
                conflict_malus = 25; conflict_label = "Ancien client — vérifier confidentialité"
            elif etype == "partie_adverse":
                conflict_malus = 30; conflict_label = "Partie adverse dans dossier actif"

    solvabilite = _pilier1_solvabilite(bodacc, pappers)
    if solvabilite["eliminated"]:
        return {
            "score": 0, "match_score": 0,
            "solvabilite": solvabilite, "capacite": {}, "trajectoire": {}, "declencheurs": [],
            "deonto_color": "rouge", "deonto_alert": True,
            "score_breakdown": {"solvabilite": solvabilite["flags"][0]["label"] if solvabilite["flags"] else "Éliminé"},
        }

    capacite = _pilier2_capacite(p, pappers)
    trajectoire = _pilier3_trajectoire(p, bodacc, pappers)
    declencheurs = _pilier4_declencheurs(p, bodacc, pappers)

    trigger_bonus = sum(t.get("score_bonus", 0) for t in declencheurs[:3])
    raw_score = (
        capacite["score"] * 0.35
        + trajectoire["score"] * 0.30
        + trigger_bonus * 0.25
        + max(0, 100 - solvabilite["score_malus"]) * 0.10
        - conflict_malus
    )
    score = max(0, min(100, int(raw_score)))

    best_bonus = declencheurs[0].get("score_bonus", 0) if declencheurs else 0
    match_score = max(0, min(100, int(capacite["score"] * 0.5 + best_bonus * 2 - solvabilite["score_malus"])))

    deonto_color = solvabilite["color"]
    if deonto_color == "vert" and (score < 25 or conflict_label):
        deonto_color = "orange"

    breakdown = {}
    if conflict_label: breakdown["conflit"] = conflict_label
    if capacite.get("naf_label"): breakdown["secteur"] = capacite["naf_label"]
    for f in solvabilite.get("flags", []): breakdown[f["type"]] = f["label"]

    return {
        "score": score, "match_score": match_score,
        "solvabilite": solvabilite, "capacite": capacite,
        "trajectoire": trajectoire, "declencheurs": declencheurs,
        "deonto_color": deonto_color, "deonto_alert": deonto_color != "vert",
        "score_breakdown": breakdown,
    }


def _fmt_montant(v) -> str:
    if v is None: return "N/A"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000: return f"{v/1_000:.0f}k"
    return str(v)


async def _load_cabinet_entities() -> list:
    entities = []
    try:
        r = supabase.table("clients").select("raison_sociale,siren,statut").execute()
        for c in (r.data or []):
            if c.get("raison_sociale"):
                entities.append({"name": c["raison_sociale"], "siren": c.get("siren"), "type": "client_actuel" if c.get("statut") in ("actif", "active", "en_cours") else "client_ancien"})
    except Exception:
        pass
    try:
        r = supabase.table("dossiers").select("partie_adverse").execute()
        for d in (r.data or []):
            if d.get("partie_adverse"):
                entities.append({"name": d["partie_adverse"], "siren": None, "type": "partie_adverse"})
    except Exception:
        pass
    return entities


@router.get("/sirene")
async def get_sirene(q: str = Query(..., min_length=2), postal_code: str = None, limit: int = 10, user=Depends(get_current_user)):
    return await search_sirene(q, postal_code=postal_code, limit=limit)


@router.get("/bodacc/{siren}")
async def get_bodacc_route(siren: str, user=Depends(get_current_user)):
    return await get_bodacc(siren)


@router.get("/pappers/{siren}")
async def get_pappers_route(siren: str, user=Depends(get_current_user)):
    return await get_pappers(siren)


@router.post("/search")
async def search_and_import(body: dict, user=Depends(get_current_user)):
    """Recherche prospects → pipeline 4 piliers → auto-save."""
    location = (body.get("location") or "").strip()
    sector = (body.get("sector") or "").strip()
    postal_code = (body.get("postal_code") or "").strip() or None
    limit = max(5, min(int(body.get("limit", 20)), 50))

    parts = [p for p in [sector, location] if p and not p.isdigit()]
    query = " ".join(parts)
    if not query and not postal_code:
        raise HTTPException(400, "Veuillez préciser au moins une localisation ou un secteur.")

    try:
        results = await search_sirene(query or "entreprise", postal_code=postal_code, limit=limit)
    except Exception as e:
        raise HTTPException(502, f"Erreur API Sirene : {e}")

    if not results:
        return {"saved": 0, "skipped_existing": 0, "skipped_error": 0, "results": [], "query": query, "message": "Aucune entreprise trouvée."}

    cabinet_entities = await _load_cabinet_entities()
    saved, skipped_existing, skipped_error = [], [], []

    for r in results:
        siren = (r.get("siren") or "").strip()
        bodacc = {"procedure": None, "events": [], "annonces": [], "procedure_recent": False}
        if siren:
            try: bodacc = await get_bodacc(siren); r["bodacc_procedure"] = bodacc.get("procedure")
            except Exception: pass

        pappers = {"available": False}
        if siren:
            try: pappers = await get_pappers(siren)
            except Exception: pass

        scoring = _score_complet(r, bodacc, pappers, cabinet_entities)
        r.update(scoring)

        if siren:
            try:
                existing = supabase.table("prospects").select("id").eq("siren", siren).limit(1).execute()
                if existing.data:
                    r["already_exists"] = True; r["db_id"] = existing.data[0]["id"]; skipped_existing.append(r); continue
            except Exception:
                pass

        try:
            capacite = scoring.get("capacite", {})
            declencheurs = scoring.get("declencheurs", [])
            record = {
                "user_id": user["id"],
                "company_name": (r.get("company_name") or "—")[:255],
                "siren": siren or None,
                "siret": r.get("siret") or None,
                "naf_code": r.get("naf_code") or None,
                "naf_label": r.get("naf_label") or capacite.get("naf_label") or None,
                "effectif_tranche": r.get("effectif_tranche") or None,
                "forme_juridique": r.get("forme_juridique") or None,
                "address": r.get("address") or None,
                "postal_code": r.get("postal_code") or postal_code or None,
                "city": r.get("city") or location or None,
                "score": scoring["score"],
                "score_breakdown": json.dumps({
                    "solvabilite_color": scoring.get("solvabilite", {}).get("color", "vert"),
                    "capacite_tranche": capacite.get("tranche"),
                    "capacite_symbol": capacite.get("symbol"),
                    "capacite_label": capacite.get("label"),
                    "capacite_honoraires": capacite.get("honoraires"),
                    "capacite_naf_label": capacite.get("naf_label"),
                    "capacite_forme_label": capacite.get("forme_label"),
                    "solvabilite_flags": scoring.get("solvabilite", {}).get("flags", []),
                    "trajectoire_signals": scoring.get("trajectoire", {}).get("signals", []),
                    "trajectoire_age_years": scoring.get("trajectoire", {}).get("age_years"),
                    "trajectoire_growth": scoring.get("trajectoire", {}).get("ca_growth_pct"),
                    "match_score": scoring.get("match_score"),
                    "declencheurs": scoring.get("declencheurs", []),
                    **scoring.get("score_breakdown", {}),
                }, ensure_ascii=False),
                "bodacc_procedure": r.get("bodacc_procedure") or None,
                "source": "scraping_sirene",
                "status": "identifie",
                "priority": "urgent" if scoring["score"] >= 75 else "normal" if scoring["score"] >= 40 else "faible",
            }
            res = supabase.table("prospects").insert(record).execute()
            if res.data:
                r["id"] = res.data[0]["id"]; r["saved"] = True; saved.append(r)
        except Exception as e:
            r["save_error"] = str(e); skipped_error.append(r)

    return {
        "saved": len(saved), "skipped_existing": len(skipped_existing), "skipped_error": len(skipped_error),
        "results": saved + skipped_existing, "query": query,
        "message": f"{len(saved)} prospect(s) importé(s) — scoring 4 piliers"
            + (f" · {len(skipped_existing)} déjà en base" if skipped_existing else "")
            + (f" · {len(skipped_error)} erreur(s)" if skipped_error else ""),
    }


@router.get("/enrich")
async def enrich(siren: str = None, siret: str = None, user=Depends(get_current_user)):
    from services.sirene import enrich_prospect
    enriched = await enrich_prospect(siren=siren, siret=siret)
    siren_key = siren or (siret[:9] if siret else None)
    if siren_key:
        bodacc = enriched.get("bodacc", {})
        pappers = enriched.get("pappers", {"available": False})
        cabinet = await _load_cabinet_entities()
        enriched["scoring"] = _score_complet(enriched, bodacc, pappers, cabinet)
    return enriched
