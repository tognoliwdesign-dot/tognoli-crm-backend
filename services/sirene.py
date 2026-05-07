"""
LEXARYS — Service Sirene (INSEE) + BODACC (DILA) + Pappers (financier)
APIs officielles / open data — conformité RGPD Art. 6.1.f
Sources :
  - INSEE Sirene V3.11 : https://api.insee.fr/entreprises/sirene/
  - recherche-entreprises.api.gouv.fr (fallback sans token)
  - BODACC Open Data DILA : bodacc-datadila.opendatasoft.com
  - Pappers (freemium) : https://api.pappers.fr/v2/ — clé PAPPERS_TOKEN
"""
import httpx
import os
from datetime import datetime, timedelta

SIRENE_TOKEN = os.getenv("INSEE_TOKEN", "")
PAPPERS_TOKEN = os.getenv("PAPPERS_TOKEN", "")
BODACC_BASE = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets"
PAPPERS_BASE = "https://api.pappers.fr/v2"


async def search_sirene(q: str, postal_code: str = None, naf_code: str = None, limit: int = 10) -> list:
    """Recherche Sirene via l'API publique INSEE, avec fallback data.gouv.fr."""
    params = {
        "q": q,
        "nombre": limit,
        "champs": (
            "siret,denominationUniteLegale,categorieEntreprise,"
            "trancheEffectifsUniteLegale,activitePrincipaleUniteLegale,"
            "dateCreationUniteLegale,categorieJuridiqueUniteLegale,"
            "etatAdministratifUniteLegale"
        ),
    }
    if postal_code:
        params["codePostalEtablissement"] = postal_code
    headers = {}
    if SIRENE_TOKEN:
        headers["Authorization"] = f"Bearer {SIRENE_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.insee.fr/entreprises/sirene/V3.11/siret",
                params=params, headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return _parse_sirene_results(data.get("etablissements", []))
    except Exception:
        pass
    return await _search_entreprise_api(q, postal_code, limit)


async def _search_entreprise_api(q: str, postal_code: str = None, limit: int = 10) -> list:
    params = {"q": q, "per_page": limit}
    if postal_code:
        params["code_postal"] = postal_code
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                "https://recherche-entreprises.api.gouv.fr/search",
                params=params,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for r in (data.get("results") or []):
                    siege = r.get("siege") or {}
                    results.append({
                        "siren": r.get("siren"),
                        "siret": siege.get("siret"),
                        "company_name": r.get("nom_raison_sociale") or r.get("nom_complet", ""),
                        "naf_code": r.get("activite_principale", ""),
                        "naf_label": r.get("libelle_activite_principale", ""),
                        "effectif_tranche": r.get("tranche_effectif_salarie", ""),
                        "forme_juridique": r.get("nature_juridique", ""),
                        "date_creation": r.get("date_creation"),
                        "city": siege.get("libelle_commune", ""),
                        "postal_code": siege.get("code_postal", ""),
                        "address": siege.get("adresse", ""),
                        "is_active": r.get("etat_administratif") == "A",
                        "source": "sirene",
                    })
                return results
    except Exception:
        pass
    return []


def _parse_sirene_results(etablissements: list) -> list:
    results = []
    for e in etablissements:
        ul = e.get("uniteLegale") or {}
        ad = e.get("adresseEtablissement") or {}
        results.append({
            "siren": e.get("siren"),
            "siret": e.get("siret"),
            "company_name": ul.get("denominationUniteLegale") or ul.get("nomUniteLegale", ""),
            "naf_code": ul.get("activitePrincipaleUniteLegale", ""),
            "effectif_tranche": ul.get("trancheEffectifsUniteLegale", ""),
            "forme_juridique": ul.get("categorieJuridiqueUniteLegale", ""),
            "date_creation": ul.get("dateCreationUniteLegale"),
            "city": ad.get("libelleCommuneEtablissement", ""),
            "postal_code": ad.get("codePostalEtablissement", ""),
            "is_active": ul.get("etatAdministratifUniteLegale") == "A",
            "source": "sirene",
        })
    return results


async def get_bodacc(siren: str) -> dict:
    siren_clean = siren.replace(" ", "").replace("-", "")[:9]
    all_records = []
    for dataset in ["bodacc-a", "bodacc-b"]:
        try:
            params = {
                "where": f'registre="{siren_clean}"',
                "order_by": "dateparution desc",
                "limit": 10,
                "select": "dateparution,typeavis,typeavis_lib,commercant,ville,cp,registre",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{BODACC_BASE}/{dataset}/records", params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    all_records.extend(data.get("results") or data.get("records") or [])
        except Exception:
            pass
    return _parse_bodacc(all_records, siren_clean)


def _parse_bodacc(records: list, siren: str) -> dict:
    PROCEDURE_MAP = {
        "SAUVEGARDE": "sauvegarde", "REDRESSEMENT": "redressement",
        "LIQUIDATION": "liquidation", "CESSION": "cession", "PLAN": "sauvegarde",
    }
    EVENT_MAP = {
        "VENTE": "cession", "CREATION": "creation", "IMMATRICULATION": "immatriculation",
        "MODIFICATION": "modification_statuts", "DISSOLUTION": "dissolution", "BILAN": "depot_comptes",
    }
    procedure = None
    procedure_date = None
    events = []
    annonces = []
    now = datetime.now()
    three_years_ago = now - timedelta(days=3 * 365)
    one_year_ago = now - timedelta(days=365)

    for r in records:
        type_avis_raw = r.get("typeavis_lib") or r.get("typeavis") or ""
        type_avis = type_avis_raw.upper()
        date_str = r.get("dateparution")
        annonce_date = None
        try:
            if date_str:
                annonce_date = datetime.fromisoformat(date_str[:10])
        except Exception:
            pass

        for keyword, proc_type in PROCEDURE_MAP.items():
            if keyword in type_avis:
                if procedure is None:
                    procedure = proc_type
                    procedure_date = annonce_date
                break

        for keyword, ev in EVENT_MAP.items():
            if keyword in type_avis:
                events.append({
                    "type": ev,
                    "date": date_str,
                    "label": type_avis_raw,
                    "recent": annonce_date is not None and annonce_date > one_year_ago,
                })
                break

        annonces.append({"date": date_str, "type": type_avis_raw, "commercant": r.get("commercant"), "ville": r.get("ville")})

    procedure_recent = (
        procedure is not None
        and procedure_date is not None
        and procedure_date > three_years_ago
    )

    return {
        "siren": siren,
        "procedure": procedure,
        "procedure_date": procedure_date.isoformat() if procedure_date else None,
        "procedure_recent": procedure_recent,
        "events": events,
        "annonces": annonces[:10],
        "has_procedure": procedure is not None,
        "has_recent_modification": any(e["type"] == "modification_statuts" and e.get("recent") for e in events),
        "has_recent_creation": any(e["type"] in ("creation", "immatriculation") for e in events),
        "has_dissolution": any(e["type"] == "dissolution" for e in events),
    }


async def get_pappers(siren: str) -> dict:
    """Enrichissement Pappers (freemium) — token PAPPERS_TOKEN requis."""
    if not PAPPERS_TOKEN:
        return {"available": False, "siren": siren}
    siren_clean = siren.replace(" ", "").replace("-", "")[:9]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PAPPERS_BASE}/entreprise",
                params={
                    "api_token": PAPPERS_TOKEN,
                    "siren": siren_clean,
                    "comptes": "true",
                    "dirigeants": "true",
                    "publications_bodacc": "false",
                    "actes": "false",
                    "beneficiaires": "false",
                },
            )
            if resp.status_code == 200:
                parsed = _parse_pappers(resp.json())
                parsed["available"] = True
                parsed["siren"] = siren_clean
                return parsed
    except Exception:
        pass
    return {"available": False, "siren": siren_clean}


def _parse_pappers(raw: dict) -> dict:
    comptes = raw.get("comptes_annuels") or raw.get("comptes") or []
    dirigeants = raw.get("dirigeants") or []
    try:
        comptes = sorted(comptes, key=lambda c: c.get("annee_cloture_exercice", "0"), reverse=True)
    except Exception:
        pass

    ca_history, resultat_history = [], []
    current_year = datetime.now().year

    for c in comptes[:4]:
        annee = c.get("annee_cloture_exercice")
        ca = c.get("chiffre_affaires") or c.get("ca") or c.get("produits_exploitation")
        resultat = c.get("resultat") or c.get("resultat_net")
        if annee and ca is not None:
            ca_history.append({"annee": annee, "valeur": ca})
        if annee and resultat is not None:
            resultat_history.append({"annee": annee, "valeur": resultat})

    latest_ca = ca_history[0]["valeur"] if ca_history else None
    previous_ca = ca_history[1]["valeur"] if len(ca_history) > 1 else None
    ca_growth_pct = None
    if latest_ca and previous_ca and previous_ca > 0:
        ca_growth_pct = round((latest_ca - previous_ca) / previous_ca * 100, 1)

    latest_resultat = resultat_history[0]["valeur"] if resultat_history else None
    last_c = comptes[0] if comptes else {}
    capitaux_propres = last_c.get("capitaux_propres")
    capital_social = last_c.get("capital_social") or last_c.get("capital")
    equity_alert = False
    if capitaux_propres is not None and capital_social and capital_social > 0:
        equity_alert = capitaux_propres < (0.5 * capital_social)

    last_accounts_year = None
    if comptes:
        try:
            last_accounts_year = int(comptes[0].get("annee_cloture_exercice", 0))
        except Exception:
            pass
    accounts_not_filed = last_accounts_year is not None and (current_year - last_accounts_year) >= 2

    dirigeant_info = []
    for d in dirigeants[:3]:
        dirigeant_info.append({
            "nom": f"{d.get('prenom', '')} {d.get('nom', '')}".strip(),
            "qualite": d.get("qualite", ""),
            "date_debut": d.get("date_prise_de_poste"),
        })

    return {
        "ca_latest": latest_ca, "ca_previous": previous_ca, "ca_growth_pct": ca_growth_pct,
        "ca_history": ca_history, "resultat_net_latest": latest_resultat, "resultat_history": resultat_history,
        "capitaux_propres": capitaux_propres, "capital_social": capital_social,
        "equity_alert": equity_alert, "accounts_not_filed": accounts_not_filed,
        "last_accounts_year": last_accounts_year, "dirigeants": dirigeant_info,
    }


async def enrich_prospect(siren: str = None, siret: str = None) -> dict:
    """Enrichit un prospect : Sirene + BODACC + Pappers."""
    enriched = {}
    search_q = siret or siren or ""
    if search_q:
        results = await search_sirene(search_q)
        if results:
            enriched.update(results[0])

    siren_to_check = siren or (siret[:9] if siret and len(siret) >= 9 else None)
    if siren_to_check:
        bodacc = await get_bodacc(siren_to_check)
        enriched["bodacc"] = bodacc
        enriched["bodacc_procedure"] = bodacc.get("procedure")
        enriched["bodacc_annonces"] = bodacc.get("annonces", [])
        pappers = await get_pappers(siren_to_check)
        if pappers.get("available"):
            enriched["pappers"] = pappers

    return enriched
