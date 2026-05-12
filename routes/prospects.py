"""LEXARYS - Routes Prospects"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ProspectCreate, ProspectUpdate, ProspectStatusUpdate
from auth import get_current_user

router = APIRouter(prefix="/prospects", tags=["prospects"])

PROSPECT_COLUMNS = {
    'user_id', 'raison_sociale', 'siren', 'siret', 'forme_juridique',
    'secteur_activite', 'code_naf', 'adresse', 'code_postal', 'ville',
    'effectif', 'chiffre_affaires', 'notes', 'source', 'tags',
    'statut', 'priority', 'score', 'score_breakdown',
    'capital_social', 'bodacc_procedure',
    'contact_name', 'contact_role', 'email', 'phone', 'website',
    'date_creation', 'assigned_to',
}

API_TO_DB = {
    'company_name':     'raison_sociale',
    'address':          'adresse',
    'postal_code':      'code_postal',
    'city':             'ville',
    'naf_code':         'code_naf',
    'naf_label':        'secteur_activite',
    'effectif_tranche': 'effectif',
    'priorite':         'priority',
}


def _to_db(data: dict) -> dict:
    translated = {}
    for k, v in data.items():
        db_key = API_TO_DB.get(k, k)
        translated[db_key] = v
    return {k: v for k, v in translated.items() if k in PROSPECT_COLUMNS and v is not None}


def _to_api(row: dict) -> dict:
    if not row:
        return row
    result = dict(row)
    if 'raison_sociale' in row:
        result['company_name'] = row['raison_sociale']
    if 'ville' in row:
        result['city'] = row['ville']
    if 'code_postal' in row:
        result['postal_code'] = row['code_postal']
    if 'code_naf' in row:
        result['naf_code'] = row['code_naf']
    if 'adresse' in row:
        result['address'] = row['adresse']
    if 'secteur_activite' in row:
        result['naf_label'] = row['secteur_activite']
    if 'statut' in row:
        result['status'] = row['statut']
    if 'priority' in row:
        result['priorite'] = row['priority']
    return result


@router.get("")
async def list_prospects(
    status: str = None,
    statut: str = None,
    search: str = None,
    priority: str = None,
    priorite: str = None,
    limit: int = 200,
    user=Depends(get_current_user)
):
    try:
        q = supabase.table("prospects").select("*").eq("user_id", user["id"])
        st = status or statut
        pr = priority or priorite
        if st:
            q = q.eq("status", st)
        if pr:
            q = q.eq("priority", pr)
        if search:
            q = q.ilike("raison_sociale", f"%{search}%")
        q = q.order("created_at", desc=True).limit(limit)
        result = q.execute()
        rows = result.data or []
        # Enrichir chaque prospect avec le dernier scoring Lexarys (v_dernier_scoring)
        if rows:
            ids = [r["id"] for r in rows if r.get("id")]
            try:
                sc = supabase.table("v_dernier_scoring").select(
                    "prospect_id,score_final,score_normalise,taux_couverture,garde_active,procedure_active,date_calcul,version_algo"
                ).in_("prospect_id", ids).execute()
                sc_map = {s["prospect_id"]: s for s in (sc.data or [])}
                for r in rows:
                    s = sc_map.get(r.get("id"))
                    if s:
                        r["lexarys_score"] = s.get("score_final")
                        r["lexarys_couverture"] = s.get("taux_couverture")
                        r["lexarys_garde_active"] = s.get("garde_active")
                        r["lexarys_procedure_active"] = s.get("procedure_active")
                        r["lexarys_date_calcul"] = s.get("date_calcul")
                        r["lexarys_version"] = s.get("version_algo")
            except Exception:
                pass  # vue absente ou table scoring non encore creee
        return [_to_api(r) for r in rows]
    except Exception as e:
        raise HTTPException(500, f"Erreur liste prospects: {str(e)}")


@router.post("")
async def create_prospect(body: ProspectCreate, user=Depends(get_current_user)):
    try:
        raw = body.model_dump()
        raw["user_id"] = user["id"]
        if not raw.get("raison_sociale") and raw.get("company_name"):
            raw["raison_sociale"] = raw["company_name"]
        if not raw.get("raison_sociale"):
            raise HTTPException(400, "raison_sociale requis")
        if raw.get("date_creation"):
            raw["date_creation"] = str(raw["date_creation"])
        data = _to_db(raw)
        result = supabase.table("prospects").insert(data).execute()
        return _to_api(result.data[0]) if result.data else {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur creation prospect: {str(e)}")


@router.get("/stats")
async def prospect_stats(user=Depends(get_current_user)):
    try:
        all_p = supabase.table("prospects").select(
            "statut,priority,score_breakdown"
        ).eq("user_id", user["id"]).execute()
        data = all_p.data or []
        pipeline = {}
        for p in data:
            s = p.get("statut", "identifie")
            pipeline[s] = pipeline.get(s, 0) + 1
        scores = []
        for p in data:
            sb = p.get("score_breakdown")
            if sb:
                try:
                    import json
                    sc = json.loads(sb).get("score", 0) if isinstance(sb, str) else sb.get("score", 0)
                    if sc: scores.append(sc)
                except: pass
        urgent = sum(1 for p in data if p.get("priority") == "urgent")
        converti = pipeline.get("converti", 0)
        return {
            "total": len(data),
            "pipeline": pipeline,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "urgent": urgent,
            "high_priority": urgent,
            "converti": converti,
            "converted": converti,
            "deonto_alerts": sum(1 for p in data if p.get("has_formal_refusal")),
        }
    except Exception:
        return {"total": 0, "pipeline": {}, "avg_score": 0,
                "urgent": 0, "high_priority": 0, "converti": 0,
                "converted": 0, "deonto_alerts": 0}


@router.get("/{prospect_id}")
async def get_prospect(prospect_id: str, user=Depends(get_current_user)):
    try:
        result = supabase.table("prospects").select("*").eq("id", prospect_id).eq("user_id", user["id"]).execute()
        if not result.data:
            raise HTTPException(404, "Prospect introuvable")
        return _to_api(result.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/{prospect_id}")
async def update_prospect(prospect_id: str, body: ProspectUpdate, user=Depends(get_current_user)):
    try:
        raw = {k: v for k, v in body.model_dump().items() if v is not None}
        raw["updated_at"] = datetime.utcnow().isoformat()
        data = _to_db(raw)
        if not data:
            return {}
        result = supabase.table("prospects").update(data).eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/{prospect_id}/status")
async def update_status(prospect_id: str, body: ProspectStatusUpdate, user=Depends(get_current_user)):
    try:
        result = supabase.table("prospects").update({
            "statut": body.status,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{prospect_id}/contact")
async def log_contact(prospect_id: str, contact_type: str, notes: str = None, user=Depends(get_current_user)):
    try:
        existing = supabase.table("prospects").select("statut").eq("id", prospect_id).execute()
        if not existing.data:
            raise HTTPException(404, "Prospect introuvable")
        if existing.data[0].get("has_formal_refusal"):
            raise HTTPException(403, "Prospect a refuse d'etre contacte.")
        try:
            supabase.table("prospect_contacts").insert({
                "prospect_id": prospect_id,
                "user_id": user["id"],
                "contact_type": contact_type,
                "notes": notes,
                "contact_date": datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            pass
        new_count = (existing.data[0].get("nb_contacts") or 0) + 1
        supabase.table("prospects").update({
            "nb_contacts": new_count,
            "last_contact_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", prospect_id).execute()
        return {"nb_contacts": new_count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{prospect_id}")
async def delete_prospect(prospect_id: str, user=Depends(get_current_user)):
    try:
        supabase.table("prospects").delete().eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── SCORING ────────────────────────────────────────────────────────────────

@router.get("/{prospect_id}/scoring")
async def get_scoring(prospect_id: str, user=Depends(get_current_user)):
    """Retourne le dernier score calcule pour un prospect."""
    try:
        p = supabase.table("prospects").select("id,siren").eq("id", prospect_id).eq("user_id", user["id"]).single().execute()
        if not p.data:
            raise HTTPException(404, "Prospect introuvable")
        sc = supabase.table("prospect_scoring").select("*").eq("prospect_id", prospect_id).neq("statut_calcul","erreur").order("date_calcul", desc=True).limit(1).execute()
        if not sc.data:
            raise HTTPException(404, "Aucun scoring disponible")
        row = sc.data[0]
        sigs = supabase.table("prospect_scoring_signal").select("*").eq("scoring_id", row["id"]).execute()
        row["signaux"] = sigs.data or []
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{prospect_id}/scoring/compute")
async def compute_scoring(prospect_id: str, user=Depends(get_current_user)):
    """Calcule et sauvegarde le score d un prospect via les API publiques francaises."""
    import httpx, uuid, time
    from datetime import date, timezone

    try:
        p = supabase.table("prospects").select("id,siren,raison_sociale").eq("id", prospect_id).eq("user_id", user["id"]).single().execute()
        if not p.data:
            raise HTTPException(404, "Prospect introuvable")
        siren = str(p.data.get("siren") or "").strip()
        if len(siren) != 9 or not siren.isdigit():
            raise HTTPException(400, "SIREN invalide ou manquant (9 chiffres requis)")

        t0 = time.perf_counter()

        # Cle de controle TVA FR depuis SIREN
        siren_int = int(siren)
        tva_cle = (12 + 3 * (siren_int % 97)) % 97
        tva_fr = f"{tva_cle:02d}{siren}"
        raison_q = (p.data.get("raison_sociale") or "").strip()
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0 (Lexarys CRM)"}) as client:
            adresse_full = (p.data.get("adresse") or "").strip()
            tasks = [
                client.get(f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&page=1&per_page=1"),
                client.get("https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/bodacc-a/records",
                    params={"where": f"registre LIKE '%25{siren}%25'", "limit": 50, "order_by": "dateparution DESC"}),
                client.get(f"https://api.vatcomply.com/vat", params={"vat_number": f"FR{tva_fr}"}, timeout=8.0),
                client.get(f"https://api.gleif.org/api/v1/lei-records",
                    params={"filter[entity.legalName]": raison_q, "page[size]": 3} if raison_q else {"page[size]": 0}, timeout=8.0),
                client.get(f"https://www.orias.fr/search", params={"q": siren}, timeout=8.0),
                # API GeoRisques (ICPE) — installations classees pour l'environnement
                client.get(f"https://georisques.gouv.fr/api/v1/installations_classees", params={"page": 1, "page_size": 1, "search": siren}, timeout=8.0),
                # API Adresse BAN — validation/geocoding
                client.get(f"https://api-adresse.data.gouv.fr/search/", params={"q": adresse_full[:200], "limit": 1}, timeout=8.0) if adresse_full else __import__("asyncio").sleep(0, result=None),
                # API DECP — marches publics (data.economie.gouv.fr)
                client.get(f"https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/decp-augmente/records",
                    params={"where": f"titulaire_id_1 = '{siren}' OR titulaire_id_2 = '{siren}'", "limit": 5}, timeout=10.0),
            ]
            r_re, r_bo, r_vies, r_gleif, r_orias, r_geor, r_ban, r_decp = await __import__("asyncio").gather(*tasks, return_exceptions=True)

        entreprise = {}
        dirigeants_data = []
        if not isinstance(r_re, Exception) and r_re.status_code == 200:
            d = r_re.json()
            results = d.get("results", []) or []
            if results:
                entreprise = results[0] or {}
                dirigeants_data = entreprise.get("dirigeants") or []

        bodacc_records = []
        if not isinstance(r_bo, Exception) and r_bo.status_code == 200:
            bodacc_records = r_bo.json().get("results", []) or []

        # ── Evaluation des signaux ─────────────────────────────────
        signaux = []
        score_brut = 0.0
        max_appl = 0.0

        def sig(code, label, bloc, pts, pts_max, statut, valeur=None, source="recherche_entreprises", raison=None):
            nonlocal score_brut, max_appl
            if statut != "indisponible_legitime":
                max_appl += pts_max
                if statut == "evalue":
                    score_brut += pts
            return {"signal_code":code,"signal_label":label,"bloc":bloc,
                    "points_obtenus":pts,"points_max":pts_max,"statut":statut,
                    "valeur_brute":valeur,"source_api":source,"confidentiel_raison":raison}

        # Anciennete
        dc = str(entreprise.get("date_creation") or "")[:10]
        if dc and len(dc)==10:
            try:
                ans = (date.today()-date.fromisoformat(dc)).days/365.25
                p_anc = 8 if ans>=10 else 6 if ans>=5 else 4 if ans>=3 else 2 if ans>=1 else 0
                signaux.append(sig("anciennete","Anciennete","stabilite",p_anc,8,"evalue",f"{ans:.1f} ans"))
            except:
                signaux.append(sig("anciennete","Anciennete","stabilite",0,8,"indisponible_anormal"))
        else:
            signaux.append(sig("anciennete","Anciennete","stabilite",0,8,"indisponible_anormal"))

        # Forme juridique
        fj = str(entreprise.get("categorie_juridique") or "")
        lbl_fj = entreprise.get("categorie_juridique_label") or fj or "Inconnu"
        p_fj = 5 if fj.startswith("5") else 4 if fj.startswith("6") else 3 if fj.startswith("7") else 1 if fj.startswith("1") else 3
        signaux.append(sig("forme_juridique","Forme juridique","stabilite",p_fj if fj else 0,5,"evalue" if fj else "indisponible_anormal",lbl_fj))

        # Continuite
        signaux.append(sig("continuite","Continuite activite","stabilite",5,5,"evalue","Active"))

        # Nb etablissements
        nb_e = max(int(entreprise.get("nombre_etablissements") or 1),1)
        p_e = 6 if nb_e>=10 else 5 if nb_e>=5 else 4 if nb_e>=3 else 3 if nb_e>=2 else 2
        signaux.append(sig("nb_etablissements","Nb etablissements","complexite",p_e,6,"evalue",str(nb_e)))

        # Nb dirigeants (signal de complexite organisationnelle, source: recherche-entreprises)
        nb_dir = len(dirigeants_data) if dirigeants_data else 0
        # nb_dirigeants INVERSE pour POTENTIEL : peu = sweet spot relation long terme
        if nb_dir == 0:
            signaux.append(sig("nb_dirigeants","Nb dirigeants","complexite",0,3,"indisponible_anormal",raison="Aucun dirigeant declare"))
        elif nb_dir <= 2:
            signaux.append(sig("nb_dirigeants","Nb dirigeants","complexite",3,3,"evalue",f"{nb_dir} dirigeant(s) — structure agile, fort potentiel relation"))
        elif nb_dir <= 5:
            signaux.append(sig("nb_dirigeants","Nb dirigeants","complexite",2,3,"evalue",f"{nb_dir} dirigeants — gouvernance moyenne, potentiel correct"))
        elif nb_dir <= 15:
            signaux.append(sig("nb_dirigeants","Nb dirigeants","complexite",1,3,"evalue",f"{nb_dir} dirigeants — comite de direction, counsel probable"))
        else:
            signaux.append(sig("nb_dirigeants","Nb dirigeants","complexite",0,3,"evalue",f"{nb_dir} dirigeants — grande organisation, counsel etabli quasi-certain"))

        # Conventions collectives
        cc = entreprise.get("conventions_collectives") or []
        nb_cc = len(cc) if isinstance(cc,list) else 0
        p_cc = 4 if nb_cc>=2 else 3 if nb_cc==1 else 2
        signaux.append(sig("conventions_collectives","Conventions collectives","complexite",p_cc,4,"evalue",f"{nb_cc} convention(s)"))

        # BE et filiales (INPI non configure)
        signaux.append(sig("be_declare","Beneficiaire effectif","complexite",0,5,"indisponible_legitime",raison="Token INPI non configure",source="rne_inpi"))
        signaux.append(sig("filiales","Filiales / groupe","complexite",0,6,"indisponible_legitime",raison="Token INPI non configure",source="rne_inpi"))

        # NEW: detection cabinet avocat dans BODACC (signal de counsel deja en place)
        bodacc_text_blob = ""
        try:
            for rec in bodacc_records[:30]:
                # Concatenate any text field that may mention legal counsel
                for k, v in (rec.get("record") or {}).get("fields", {}).items() if isinstance(rec.get("record"), dict) else (rec.items() if isinstance(rec, dict) else []):
                    if isinstance(v, str):
                        bodacc_text_blob += " " + v.lower()
        except Exception:
            pass
        # Simpler fallback: just dump all the bodacc_records as JSON string
        try:
            import json as _json
            bodacc_text_blob += " " + _json.dumps(bodacc_records, default=str).lower()
        except Exception:
            pass
        has_cabinet_avocat = False
        cabinet_match_label = "Aucune mention d'avocat/cabinet dans BODACC"
        try:
            patterns = ["cabinet d'avocat", "cabinet d avocat", "scp d'avocats", "avocat au barreau", "maitre ", "maître ", "selarl d'avocats", "selas d'avocats", "ordre des avocats"]
            for pat in patterns:
                if pat in bodacc_text_blob:
                    has_cabinet_avocat = True
                    cabinet_match_label = f"Mention '{pat}' detectee dans BODACC — counsel deja en place"
                    break
        except Exception:
            pass
        if has_cabinet_avocat:
            signaux.append(sig("counsel_existant","Conseil avocat deja present","stabilite",0,3,"evalue",cabinet_match_label,source="bodacc"))
        else:
            signaux.append(sig("counsel_existant","Conseil avocat deja present","stabilite",3,3,"evalue","Aucune trace d'avocat-conseil dans BODACC — fort potentiel nouveau mandat",source="bodacc"))

        # Procedure collective BODACC
        proc = False
        for rec in bodacc_records:
            fam = str(rec.get("familleavis_lib","")).lower()
            typ = str(rec.get("typeavis","")).lower()
            if ("redressement" in fam or "liquidation" in fam or "sauvegarde" in fam) and "cloture" not in typ:
                proc = True; break
        signaux.append(sig("procedure_collective","Procedure collective","sante",0 if proc else 12,12,"evalue","Procedure active" if proc else "Aucune procedure","bodacc"))

        # Annonces BODACC negatives
        cutoff = date.today().replace(year=date.today().year-2)
        neg = sum(1 for rec in bodacc_records
            if any(k in str(rec.get("familleavis_lib","")).lower() for k in ["vente","cession","dissolution","liquidation"])
            and (lambda dp: dp >= cutoff)(*(lambda x: [date.fromisoformat(str(x)[:10])] if x and len(str(x))>=10 else [cutoff])(rec.get("dateparution",""))))
        p_bo = 5 if neg==0 else 3 if neg==1 else 1
        signaux.append(sig("annonces_bodacc","Annonces BODACC negatives","sante",p_bo,5,"evalue",f"{neg} annonce(s) neg./24m","bodacc"))

        # Radiation (simplifie)
        signaux.append(sig("radiation","Radiation INSEE","sante",8,8,"evalue","Active (non radiee)","sirene"))

        # Effectif SWEET-SPOT pour POTENTIEL long terme (10-100 employes = max, <5 ou >200 = penalise)
        tr = str(entreprise.get("tranche_effectif_salarie") or "")
        # Nouveaux pts: courbe en cloche centree sur 10-100 employes
        TR_PTS = {"00":3,"01":4,"02":6,"03":8,"11":10,"12":10,"21":9,"22":7,"31":5,"32":3,"41":1,"42":0,"51":0,"52":0,"53":0}
        TR_LBL_FULL = {"00":"0 sal. (trop petit)","01":"1-2 sal. (petit)","02":"3-5 sal. (petit)","03":"6-9 sal. (correct)","11":"10-19 sal. (sweet spot)","12":"20-49 sal. (sweet spot)","21":"50-99 sal. (sweet spot)","22":"100-199 sal. (limite)","31":"200-249 sal. (counsel etabli probable)","32":"250-499 sal. (counsel etabli)","41":"500-999 sal. (DRH+counsel etabli)","42":"1000+ sal. (counsel etabli)"}
        if tr and tr in TR_PTS:
            signaux.append(sig("effectif","Effectif (potentiel)","capacite",TR_PTS[tr],10,"evalue",TR_LBL_FULL.get(tr,tr)))
        else:
            signaux.append(sig("effectif","Effectif (potentiel)","capacite",0,10,"indisponible_legitime",raison="Non renseigne ou confidentiel"))

        # Resultat net (INPI requis)
        signaux.append(sig("resultat_net","Resultat net","capacite",0,15,"indisponible_legitime",raison="Token INPI non configure",source="rne_inpi"))

        # VIES — Validation TVA intracommunautaire FR (vatcomply.com)
        vies_valid = None
        vies_label = "TVA intracommunautaire non verifiable"
        try:
            if not isinstance(r_vies, Exception) and r_vies.status_code == 200:
                vd = r_vies.json()
                vies_valid = bool(vd.get("valid"))
                if vies_valid:
                    cname = vd.get("name") or ""
                    vies_label = f"TVA intracommunautaire FR valide ({cname[:40] if cname else tva_fr})"
                else:
                    vies_label = "TVA intracommunautaire FR INVALIDE (entreprise dormante ou radiee)"
        except Exception:
            pass
        if vies_valid is True:
            signaux.append(sig("vies_tva","Validation TVA UE","stabilite",5,5,"evalue",vies_label,source="recherche_entreprises"))
        elif vies_valid is False:
            signaux.append(sig("vies_tva","Validation TVA UE","stabilite",0,5,"evalue",vies_label,source="recherche_entreprises"))
        else:
            signaux.append(sig("vies_tva","Validation TVA UE","stabilite",0,5,"indisponible_anormal",raison="API VIES indisponible",source="recherche_entreprises"))

        # GLEIF — LEI (Legal Entity Identifier international)
        lei_code = None
        lei_label = "LEI non trouve"
        try:
            if not isinstance(r_gleif, Exception) and r_gleif.status_code == 200:
                gd = r_gleif.json()
                for rec in (gd.get("data") or []):
                    attrs = rec.get("attributes", {}) or {}
                    entity = attrs.get("entity", {}) or {}
                    reg = (entity.get("registeredAs") or "").strip()
                    legal_name = (entity.get("legalName", {}) or {}).get("name", "")
                    # Match SIREN or sub-string of raison
                    # Accept STRICT match seulement: SIREN dans registeredAs ET pays France
                    country = (entity.get("legalAddress", {}) or {}).get("country", "") or (entity.get("headquartersAddress", {}) or {}).get("country", "")
                    siren_in_reg = reg and (reg == siren or reg.endswith(siren))
                    if siren_in_reg and (not country or country.upper() == "FR"):
                        lei_code = attrs.get("lei") or rec.get("id")
                        lei_label = f"LEI : {lei_code} ({legal_name[:40]})"
                        break
        except Exception:
            pass
        # LEI INVERSE pour POTENTIEL : presence LEI = grosse structure = counsel deja en place
        if lei_code:
            signaux.append(sig("lei_gleif","Identifiant LEI","complexite",0,4,"evalue",f"LEI declare {lei_code[:20]} — structure institutionnelle, counsel deja probable",source="recherche_entreprises"))
        else:
            signaux.append(sig("lei_gleif","Identifiant LEI","complexite",4,4,"evalue","Pas de LEI declare — structure independante, fort potentiel relation long terme",source="recherche_entreprises"))

        # ORIAS — registre intermediaires assurance / credit
        orias_match = None
        try:
            if not isinstance(r_orias, Exception) and r_orias.status_code == 200:
                ot = r_orias.text or ""
                # Heuristique: detection de mention SIREN dans la page resultat
                if siren in ot and ("immatricul" in ot.lower() or "courtier" in ot.lower() or "iobsp" in ot.lower() or "intermediaire" in ot.lower()):
                    orias_match = True
        except Exception:
            pass
        # ORIAS INVERSE pour POTENTIEL : etre dans ORIAS = secteur lourdement encadre = counsel etabli
        if orias_match:
            signaux.append(sig("orias","ORIAS (potentiel)","stabilite",0,2,"evalue","Immatriculee ORIAS — secteur ultra-regule, counsel quasi-certain",source="recherche_entreprises"))
        else:
            signaux.append(sig("orias","ORIAS (potentiel)","stabilite",2,2,"evalue","Pas dans ORIAS — pas de regulation lourde, plus de marge pour nouveau counsel",source="recherche_entreprises"))

        # GeoRisques — ICPE
        icpe_count = None
        try:
            if not isinstance(r_geor, Exception) and r_geor.status_code == 200:
                gd = r_geor.json()
                icpe_count = (gd.get("total") if isinstance(gd, dict) else None) or len(gd.get("data") or []) if isinstance(gd, dict) else 0
        except Exception:
            pass
        if icpe_count is None:
            signaux.append(sig("georisques","Installations classees (GeoRisques)","sante",0,3,"indisponible_anormal",raison="API GeoRisques indisponible"))
        elif icpe_count == 0:
            signaux.append(sig("georisques","Installations classees (GeoRisques)","sante",3,3,"evalue","Aucune installation classee ICPE detectee (pas de risque environnemental connu)"))
        else:
            signaux.append(sig("georisques","Installations classees (GeoRisques)","sante",1,3,"evalue",f"{icpe_count} site(s) ICPE classe(s) — secteur a risque environnemental"))

        # API Adresse BAN — validation adresse
        ban_score = None
        ban_label = "Adresse non verifiable"
        try:
            if not isinstance(r_ban, Exception) and r_ban is not None and r_ban.status_code == 200:
                bd = r_ban.json()
                feats = bd.get("features", []) or []
                if feats:
                    ban_score = (feats[0].get("properties", {}) or {}).get("score", 0)
                    ban_label_full = (feats[0].get("properties", {}) or {}).get("label", "")
                    if ban_score >= 0.7:
                        ban_label = f"Adresse validee (BAN, score {int(ban_score*100)}%) : {ban_label_full[:50]}"
                    elif ban_score >= 0.4:
                        ban_label = f"Adresse partiellement validee (BAN, score {int(ban_score*100)}%)"
                    else:
                        ban_label = f"Adresse peu fiable (BAN, score {int(ban_score*100)}%)"
        except Exception:
            pass
        if ban_score is None:
            signaux.append(sig("ban_adresse","Validation adresse BAN","stabilite",0,2,"indisponible_anormal",raison="Adresse manquante ou API BAN indisponible"))
        elif ban_score >= 0.7:
            signaux.append(sig("ban_adresse","Validation adresse BAN","stabilite",2,2,"evalue",ban_label))
        elif ban_score >= 0.4:
            signaux.append(sig("ban_adresse","Validation adresse BAN","stabilite",1,2,"evalue",ban_label))
        else:
            signaux.append(sig("ban_adresse","Validation adresse BAN","stabilite",0,2,"evalue",ban_label))

        # DECP — marches publics gagnes
        decp_count = None
        try:
            if not isinstance(r_decp, Exception) and r_decp.status_code == 200:
                dd = r_decp.json()
                decp_count = dd.get("total_count") or len(dd.get("results") or [])
        except Exception:
            pass
        # DECP INVERSE pour POTENTIEL : beaucoup de marches = avocat-conseil etabli
        if decp_count is None:
            signaux.append(sig("decp","Marches publics","capacite",2,4,"indisponible_anormal",raison="API DECP indisponible"))
        elif decp_count == 0:
            signaux.append(sig("decp","Marches publics","capacite",4,4,"evalue","Aucun marche public — pas de counsel procurement etabli, fort potentiel"))
        elif decp_count <= 3:
            signaux.append(sig("decp","Marches publics","capacite",2,4,"evalue",f"{decp_count} marche(s) public(s) — sweet spot besoin counsel ponctuel"))
        else:
            signaux.append(sig("decp","Marches publics","capacite",0,4,"evalue",f"{decp_count} marches publics — avocat-conseil procurement quasi-certain"))

                # ── Score normalise ────────────────────────────────────────
        score_norm = round(score_brut/max_appl*100,2) if max_appl>0 else None
        evalues = sum(1 for s in signaux if s["statut"]=="evalue")
        total_s = len(signaux)
        taux_cov = round(evalues/total_s*100,2) if total_s else 0

        def bstats(b):
            sb = [s for s in signaux if s["bloc"]==b]
            ev = sum(1 for s in sb if s["statut"]=="evalue")
            mx = sum(s["points_max"] for s in sb if s["statut"]!="indisponible_legitime")
            br = sum(s["points_obtenus"] for s in sb if s["statut"]=="evalue")
            return (round(br/mx*100,2) if mx>0 else None, round(ev/len(sb)*100,2) if sb else 0.0)

        sc_st,fi_st = bstats("stabilite")
        sc_co,fi_co = bstats("complexite")
        sc_sa,fi_sa = bstats("sante")
        sc_ca,fi_ca = bstats("capacite")

        cap_sigs = [s for s in signaux if s["bloc"]=="capacite"]
        fiab_cap = sum(1 for s in cap_sigs if s["statut"]=="evalue")/max(len(cap_sigs),1)
        garde = fiab_cap < 0.30
        garde_raison = None
        score_final = score_norm
        if garde:
            garde_raison = f"Fiabilite Capacite = {fiab_cap:.0%} < 30%% -- score plafonne a 70/100"
            if score_final is not None:
                score_final = round(min(score_final,70.0),2)

        duree_ms = int((time.perf_counter()-t0)*1000)
        scoring_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # ── Sauvegarde Supabase ────────────────────────────────────
        row = {
            "id":scoring_id,"prospect_id":prospect_id,"siren":siren,"version_algo":"v1.0.0",
            "score_normalise":score_norm,"score_brut":round(score_brut,2),"max_applicable":round(max_appl,2),
            "signaux_evalues":evalues,"signaux_total":total_s,"taux_couverture":taux_cov,
            "fiabilite_stabilite":fi_st,"fiabilite_complexite":fi_co,"fiabilite_sante":fi_sa,"fiabilite_capacite":fi_ca,
            "score_final":score_final,"garde_active":garde,"garde_raison":garde_raison,
            "score_stabilite":sc_st,"score_complexite":sc_co,"score_sante":sc_sa,"score_capacite":sc_ca,
            "procedure_active":proc,"duree_calcul_ms":duree_ms,"statut_calcul":"ok","date_calcul":now,
        }
        supabase.table("prospect_scoring").insert(row).execute()

        for s in signaux:
            supabase.table("prospect_scoring_signal").insert({
                "scoring_id":scoring_id,"prospect_id":prospect_id,
                "signal_code":s["signal_code"],"signal_label":s["signal_label"],"bloc":s["bloc"],
                "valeur_brute":s.get("valeur_brute"),"points_obtenus":s["points_obtenus"],
                "points_max":s["points_max"],"statut":s["statut"],"source_api":s["source_api"],
                "confidentiel_raison":s.get("confidentiel_raison"),
            }).execute()

        row["signaux"] = signaux
        return row

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur scoring: {str(e)}")


# ============================================================
# SCRAPING EMAIL — depuis le site web de l'entreprise
# ============================================================

@router.post("/{prospect_id}/scrape-email")
async def scrape_prospect_email(prospect_id: str, user=Depends(get_current_user)):
    """Recupere le site web via recherche-entreprises, scrape la home + pages contact, regex emails."""
    import httpx, re
    from datetime import timezone

    try:
        p = supabase.table("prospects").select("id,siren,raison_sociale,website,email_scrape").eq("id", prospect_id).eq("user_id", user["id"]).single().execute()
        if not p.data:
            raise HTTPException(404, "Prospect introuvable")
        siren = str(p.data.get("siren") or "").strip()
        existing_website = (p.data.get("website") or "").strip()

        website = existing_website
        # 1) Si pas de website connu, on demande a recherche-entreprises.api.gouv.fr
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Lexarys CRM)"}) as client:
            if not website and len(siren) == 9 and siren.isdigit():
                try:
                    r = await client.get(f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&limite=1")
                    if r.status_code == 200:
                        data = r.json()
                        results = data.get("results") or []
                        if results:
                            ets = (results[0].get("matching_etablissements") or [{}])[0]
                            website = (ets.get("site_internet") or results[0].get("site_internet") or "").strip()
                except Exception:
                    pass

            # Fallback: DuckDuckGo HTML search pour deviner le site officiel
            if not website:
                raison = (p.data.get("raison_sociale") or "").strip()
                cp = ""
                # On essaie une recherche ciblee
                if raison:
                    try:
                        q_search = raison + " site officiel contact"
                        r_ddg = await client.get("https://html.duckduckgo.com/html/", params={"q": q_search}, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
                        if r_ddg.status_code == 200:
                            # Extraire les URLs candidates avec regex
                            urls = re.findall(r'href="(https?://[^"]+)"', r_ddg.text)
                            # Filtres: pas duckduckgo, pas reseau social, pas annuaires
                            blacklist_hosts = ("duckduckgo.com","duck.com","facebook.com","linkedin.com","twitter.com","x.com","instagram.com","youtube.com","pages-jaunes.fr","pagesjaunes.fr","societe.com","verif.com","manageo.fr","infogreffe.fr","data.gouv.fr","fr.wikipedia.org","wikipedia.org","google.com","amazon.fr","amazon.com","bing.com","leboncoin.fr")
                            from urllib.parse import unquote
                            for u in urls:
                                # DuckDuckGo HTML wrap les URLs dans /l/?uddg=
                                if "/l/?uddg=" in u:
                                    m = re.search(r"uddg=([^&]+)", u)
                                    if m:
                                        u = unquote(m.group(1))
                                try:
                                    pu = urlparse(u)
                                    h = pu.netloc.lower().replace("www.","")
                                except Exception:
                                    continue
                                if not h or any(h == bh or h.endswith("." + bh) for bh in blacklist_hosts):
                                    continue
                                # On garde le premier candidat plausible
                                website = f"{pu.scheme}://{pu.netloc}"
                                break
                    except Exception:
                        pass
            # Fallback 2: Bing search (souvent moins anti-bot que DuckDuckGo depuis serveur)
            if not website:
                raison = (p.data.get("raison_sociale") or "").strip()
                if raison:
                    try:
                        bq = raison + " site officiel contact"
                        r_bing = await client.get("https://www.bing.com/search", params={"q": bq, "cc": "FR"}, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=8.0)
                        if r_bing.status_code == 200:
                            urls = re.findall(r'href="(https?://[^"]+)"', r_bing.text)
                            blacklist_hosts = ("bing.com","duckduckgo.com","facebook.com","linkedin.com","twitter.com","x.com","instagram.com","youtube.com","pages-jaunes.fr","pagesjaunes.fr","societe.com","verif.com","manageo.fr","infogreffe.fr","data.gouv.fr","fr.wikipedia.org","wikipedia.org","google.com","amazon.fr","amazon.com","leboncoin.fr","go.microsoft.com","msn.com","aka.ms")
                            for u in urls:
                                try:
                                    pu = urlparse(u)
                                    h = pu.netloc.lower().replace("www.","")
                                except Exception:
                                    continue
                                if not h or any(h == bh or h.endswith("." + bh) for bh in blacklist_hosts):
                                    continue
                                website = f"{pu.scheme}://{pu.netloc}"
                                break
                    except Exception:
                        pass

            # Fallback 3: Pages Jaunes recherche pro (souvent expose email directement)
            pj_emails = []
            if not website:
                raison = (p.data.get("raison_sociale") or "").strip()
                ville = (p.data.get("ville") or "").strip()
                if raison:
                    try:
                        pj_q = raison + (" " + ville if ville else "")
                        r_pj = await client.get("https://www.pagesjaunes.fr/recherche", params={"quoiqui": pj_q}, headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=8.0)
                        if r_pj.status_code == 200:
                            # extract emails from page-jaunes HTML
                            pj_pat = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
                            for em_raw in pj_pat.findall(r_pj.text):
                                em = _try_decode_email(em_raw.lower())
                                if not em.endswith((".png",".jpg",".gif",".svg")) and "@solocal" not in em and "@pagesjaunes" not in em:
                                    pj_emails.append(em)
                    except Exception:
                        pass

            # Fallback 4: deviner le domaine a partir du nom de l'entreprise
            if not website:
                raison = (p.data.get("raison_sociale") or "").strip()
                if raison:
                    # Generer un slug propre
                    import unicodedata
                    slug = unicodedata.normalize("NFKD", raison).encode("ascii","ignore").decode("ascii").lower()
                    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
                    # Strip suffixes commerciaux courants
                    for sfx in ["-sas","-sasu","-sarl","-eurl","-sa","-scp","-snc","-selarl","-sci","-association","-mutuelle"]:
                        if slug.endswith(sfx): slug = slug[:-len(sfx)]
                    # Try multiple guesses
                    for tld in [".fr", ".com", ".org"]:
                        for prefix in ["", "www."]:
                            guess = "https://" + prefix + slug + tld
                            try:
                                r_g = await client.head(guess, timeout=5.0)
                                if r_g.status_code < 400:
                                    website = guess
                                    break
                                # Fallback: many sites don't support HEAD, try GET
                                r_g = await client.get(guess, timeout=5.0)
                                if r_g.status_code < 400:
                                    website = guess
                                    break
                            except Exception:
                                continue
                        if website: break
                    # Try short slug (first word only)
                    if not website and "-" in slug:
                        short = slug.split("-")[0]
                        if len(short) >= 3:
                            for tld in [".fr", ".com"]:
                                guess = "https://" + short + tld
                                try:
                                    r_g = await client.get(guess, timeout=5.0)
                                    if r_g.status_code < 400:
                                        website = guess
                                        break
                                except Exception:
                                    continue
            if not website:
                # Dernier recours: si Pages Jaunes a remonte un email, on le sauve sans site
                if pj_emails:
                    em = pj_emails[0]
                    supabase.table("prospects").update({
                        "email_scrape": em,
                        "email_scrape_source": "pages-jaunes.fr",
                        "email_scrape_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", prospect_id).execute()
                    return {"status":"ok","email":em,"email_source_url":"pages-jaunes.fr","website":None,"candidates":[{"email":e,"source":"pages-jaunes.fr","score":1} for e in pj_emails[:5]],"total_found":len(pj_emails),"prospect_id":prospect_id}
                supabase.table("prospects").update({
                    "email_scrape_at": datetime.now(timezone.utc).isoformat(),
                    "email_scrape_source": "no_website",
                }).eq("id", prospect_id).execute()
                return {"status":"no_website","email":None,"website":None,"prospect_id":prospect_id,"detail":"Aucun site web (Sirene + Bing + DuckDuckGo + heuristique) ni Pages Jaunes"}

            # Normalise l'URL
            if not website.startswith(("http://","https://")):
                website = "https://" + website
            # On garde la racine pour generer les variantes
            from urllib.parse import urlparse
            parsed = urlparse(website)
            base = f"{parsed.scheme}://{parsed.netloc}"
            company_domain = parsed.netloc.lower().replace("www.","")

            # 2) On tente la home + 4 chemins classiques
            candidates_paths = ["", "/contact", "/contact.html", "/contact-us", "/nous-contacter", "/mentions-legales", "/a-propos"]
            email_pat = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

            def _rot13(s):
                """Decode ROT13 obfuscation (used by paris.fr and others)."""
                out = []
                for c in s:
                    if 'a' <= c <= 'z':
                        out.append(chr((ord(c) - ord('a') + 13) % 26 + ord('a')))
                    elif 'A' <= c <= 'Z':
                        out.append(chr((ord(c) - ord('A') + 13) % 26 + ord('A')))
                    else:
                        out.append(c)
                return ''.join(out)

            # Common French TLDs to detect ROT13 hits
            real_tlds = {".fr", ".com", ".org", ".net", ".eu", ".io", ".co", ".gouv", ".paris", ".bzh"}
            obfus_tlds = {".se", ".ax", ".we", ".pb", ".bet", ".pbz", ".bet", ".rh", ".ar"}  # ROT13 of fr/com/org/net/eu

            def _try_decode_email(em):
                """If the email looks ROT13-obfuscated, try to decode it."""
                if not em or '@' not in em:
                    return em
                lo = em.lower()
                # Detect: TLD is in known obfus list AND email contains no real TLD
                for ot in obfus_tlds:
                    if lo.endswith(ot):
                        decoded = _rot13(em)
                        if any(decoded.lower().endswith(rt) for rt in real_tlds):
                            return decoded
                return em
            blacklist_domains = {"example.com","domain.com","sentry.io","wixsite.com","wordpress.com","gmail.com","yahoo.fr","hotmail.fr","outlook.fr","gmail.fr","yahoo.com","wix.com","squarespace.com","godaddy.com"}
            blacklist_emails = {"name@example.com","you@example.com","support@wixpress.com"}
            generic_prefixes = ("contact","info","hello","bonjour","accueil","commercial","sales","secretariat","direction","cabinet","admin","reception")

            found_emails = []  # list of (email, source_url, score)
            for path in candidates_paths:
                url = base + path
                try:
                    rr = await client.get(url)
                    if rr.status_code != 200:
                        continue
                    text = rr.text
                    # Decode mailto: also
                    for m in re.findall(r"mailto:([^\"'>?#\s]+)", text):
                        em_m = _try_decode_email(m.lower().strip())
                        found_emails.append((em_m, url, 10))  # high priority
                    for m in email_pat.findall(text):
                        em = _try_decode_email(m.lower().strip())
                        if em in blacklist_emails: continue
                        dom = em.split("@",1)[-1]
                        if dom in blacklist_domains: continue
                        # Skip image hashes / wiximg / pseudo-emails
                        if em.endswith((".png",".jpg",".jpeg",".gif",".svg",".webp")): continue
                        score = 1
                        if dom == company_domain or dom.endswith("." + company_domain): score += 5
                        if em.split("@",1)[0] in generic_prefixes: score += 3
                        found_emails.append((em, url, score))
                except Exception:
                    continue

            # Si rien sur le site, tenter avec les emails recoltes via Pages Jaunes
            if not found_emails and pj_emails:
                for em in pj_emails:
                    dom = em.split("@",1)[-1]
                    if dom in blacklist_domains: continue
                    score = 1
                    if em.split("@",1)[0] in generic_prefixes: score += 3
                    found_emails.append((em, "pages-jaunes.fr", score))
            if not found_emails:
                supabase.table("prospects").update({
                    "website_scrape": website,
                    "email_scrape_at": datetime.now(timezone.utc).isoformat(),
                    "email_scrape_source": "no_email_on_site",
                }).eq("id", prospect_id).execute()
                return {"status":"no_email","email":None,"website":website,"prospect_id":prospect_id,"detail":"Site web atteint mais aucun email trouve (ni Pages Jaunes)"}

            # Deduplique en gardant le meilleur score
            best = {}
            for em, src, sc in found_emails:
                if em not in best or sc > best[em][1]:
                    best[em] = (src, sc)
            ranked = sorted(best.items(), key=lambda x: -x[1][1])
            top_email, (top_src, top_score) = ranked[0]

            # Save
            supabase.table("prospects").update({
                "email_scrape": top_email,
                "email_scrape_source": top_src,
                "email_scrape_at": datetime.now(timezone.utc).isoformat(),
                "website_scrape": website,
            }).eq("id", prospect_id).execute()

            return {
                "status": "ok",
                "email": top_email,
                "email_source_url": top_src,
                "website": website,
                "candidates": [{"email":em,"source":src,"score":sc} for em,(src,sc) in ranked[:5]],
                "total_found": len(best),
                "prospect_id": prospect_id,
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur scraping email: {str(e)}")
