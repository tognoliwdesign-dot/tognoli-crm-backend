"""
LEXARYS — Service Sirene (API INSEE) + BODACC (Open Data Dila)
APIs publiques gratuites — conformité RGPD
"""
import httpx
import os
from typing import Optional

SIRENE_TOKEN = os.getenv("INSEE_TOKEN", "")
BODACC_BASE = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets"

async def search_sirene(q: str, postal_code: str = None, naf_code: str = None, limit: int = 10) -> list:
    params = {"q": q, "nombre": limit, "champs": "siret,denominationUniteLegale,categorieEntreprise,trancheEffectifsUniteLegale,activitePrincipaleUniteLegale,dateCreationUniteLegale,categorieJuridiqueUniteLegale,etatAdministratifUniteLegale"}
    if postal_code: params["codePostalEtablissement"] = postal_code
    headers = {}
    if SIRENE_TOKEN: headers["Authorization"] = f"Bearer {SIRENE_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.insee.fr/entreprises/sirene/V3.11/siret", params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return _parse_sirene_results(data.get("etablissements", []))
    except Exception:
        pass
    return await _search_entreprise_api(q, postal_code, limit)

async def _search_entreprise_api(q: str, postal_code: str = None, limit: int = 10) -> list:
    params = {"q": q, "per_page": limit}
    if postal_code: params["code_postal"] = postal_code
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://recherche-entreprises.api.gouv.fr/search", params=params)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for r in (data.get("results") or []):
                    siege = r.get("siege") or {}
                    results.append({"siren": r.get("siren"), "siret": siege.get("siret"), "company_name": r.get("nom_raison_sociale") or r.get("nom_complet",""), "naf_code": r.get("activite_principale",""), "naf_label": r.get("libelle_activite_principale",""), "effectif_tranche": r.get("tranche_effectif_salarie",""), "forme_juridique": r.get("nature_juridique",""), "date_creation": r.get("date_creation"), "city": siege.get("libelle_commune",""), "postal_code": siege.get("code_postal",""), "address": siege.get("adresse",""), "is_active": r.get("etat_administratif")=="A", "source": "sirene"})
                return results
    except Exception:
        pass
    return []

def _parse_sirene_results(etablissements: list) -> list:
    results = []
    for e in etablissements:
        ul = e.get("uniteLegale") or {}
        ad = e.get("adresseEtablissement") or {}
        results.append({"siren": e.get("siren"), "siret": e.get("siret"), "company_name": ul.get("denominationUniteLegale") or ul.get("nomUniteLegale",""), "naf_code": ul.get("activitePrincipaleUniteLegale",""), "effectif_tranche": ul.get("trancheEffectifsUniteLegale",""), "forme_juridique": ul.get("categorieJuridiqueUniteLegale",""), "date_creation": ul.get("dateCreationUniteLegale"), "city": ad.get("libelleCommuneEtablissement",""), "postal_code": ad.get("codePostalEtablissement",""), "is_active": ul.get("etatAdministratifUniteLegale")=="A", "source": "sirene"})
    return results

async def get_bodacc(siren: str) -> dict:
    siren_clean = siren.replace(" ","").replace("-","")[:9]
    try:
        params = {"where": f'registre="{siren_clean}"', "order_by": "dateparution desc", "limit": 5, "select": "dateparution,typeavis,typeavis_lib,commercant,ville,cp,registre"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BODACC_BASE}/bodacc-a/records", params=params)
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("results") or data.get("records") or []
                return _parse_bodacc(records, siren_clean)
    except Exception:
        pass
    return {"siren": siren_clean, "procedure": None, "annonces": []}

def _parse_bodacc(records: list, siren: str) -> dict:
    PROCEDURE_TYPES = {"SAUVEGARDE": "sauvegarde", "REDRESSEMENT": "redressement", "LIQUIDATION": "liquidation", "CESSION": "cession", "PLAN": "sauvegarde"}
    procedure = None
    annonces = []
    for r in records:
        type_avis = (r.get("typeavis") or r.get("typeavis_lib") or "").upper()
        for keyword, proc_type in PROCEDURE_TYPES.items():
            if keyword in type_avis: procedure = proc_type; break
        annonces.append({"date": r.get("dateparution"), "type": r.get("typeavis_lib") or r.get("typeavis"), "commercant": r.get("commercant"), "ville": r.get("ville")})
    return {"siren": siren, "procedure": procedure, "annonces": annonces, "has_procedure": procedure is not None}

async def enrich_prospect(siren: str = None, siret: str = None) -> dict:
    enriched = {}
    search_q = siret or siren or ""
    if search_q:
        results = await search_sirene(search_q)
        if results: enriched.update(results[0])
    siren_to_check = siren or (siret[:9] if siret and len(siret) >= 9 else None)
    if siren_to_check:
        bodacc = await get_bodacc(siren_to_check)
        enriched["bodacc_procedure"] = bodacc.get("procedure")
        enriched["bodacc_annonces"] = bodacc.get("annonces", [])
    return enriched
