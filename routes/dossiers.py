"""LEXARYS -- Routes Dossiers (schema DB reel)"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import DossierCreate, DossierUpdate
from auth import get_current_user
import random, string

router = APIRouter(prefix="/dossiers", tags=["dossiers"])

DOSSIER_COLUMNS = {
    'user_id', 'client_id', 'reference', 'intitule', 'type_affaire',
    'juridiction', 'statut', 'date_ouverture', 'date_cloture',
    'description', 'notes', 'partie_adverse', 'created_at',
}

API_TO_DB = {
    'avocat_id':             'user_id',
    'type_dossier':          'type_affaire',
    'status':                'statut',
    'matiere':               'description',
    'partie_adverse_name':   'partie_adverse',
    'partie_adverse_siret':  None,
    'description':           'intitule',
    'conflict_check_done':   None,
    'conflict_check_date':   None,
    'conflict_check_result': None,
}


def _to_db(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        db_key = API_TO_DB.get(k, k)
        if db_key is None:
            continue
        if v is not None:
            result[db_key] = v
    return {k: v for k, v in result.items() if k in DOSSIER_COLUMNS and v is not None}


def _to_api(row: dict) -> dict:
    if not row:
        return row
    r = dict(row)
    if 'statut' in r:
        r['status'] = r['statut']
    if 'type_affaire' in r:
        r['type_dossier'] = r['type_affaire']
    if 'intitule' in r:
        r['description'] = r['intitule']
    if 'partie_adverse' in r:
        r['partie_adverse_name'] = r['partie_adverse']
    if 'user_id' in r:
        r['avocat_id'] = r['user_id']
    return r


def _generate_reference() -> str:
    year = datetime.now().year
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"LEX-{year}-{suffix}"


@router.get("")
async def list_dossiers(status: str = None, client_id: str = None, limit: int = 100, user=Depends(get_current_user)):
    try:
        q = supabase.table("dossiers").select("*")
        if status:
            q = q.eq("statut", status)
        if client_id:
            q = q.eq("client_id", client_id)
        q = q.order("created_at", desc=True).limit(limit)
        rows = q.execute().data or []
        return [_to_api(r) for r in rows]
    except Exception as e:
        raise HTTPException(500, f"Erreur liste dossiers: {str(e)}")


@router.post("")
async def create_dossier(body: DossierCreate, user=Depends(get_current_user)):
    try:
        raw = body.model_dump()
        raw["user_id"] = user["id"]
        raw["reference"] = raw.get("reference") or _generate_reference()
        if raw.get("date_ouverture"):
            raw["date_ouverture"] = str(raw["date_ouverture"])
        data = _to_db(raw)
        result = supabase.table("dossiers").insert(data).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, f"Erreur creation dossier: {str(e)}")


@router.get("/stats")
async def dossier_stats(user=Depends(get_current_user)):
    try:
        all_d = supabase.table("dossiers").select("statut,type_affaire").execute()
        data = all_d.data or []
        statuts = {}
        types = {}
        for d in data:
            s = d.get("statut", "ouvert")
            statuts[s] = statuts.get(s, 0) + 1
            t = d.get("type_affaire", "autre")
            types[t] = types.get(t, 0) + 1
        return {
            "total": len(data),
            "ouverts": statuts.get("ouvert", 0),
            "clotures": statuts.get("cloture", 0),
            "by_type": types,
            "sans_verification_conflit": 0,
            "conflits_detectes": 0,
        }
    except Exception:
        return {"total": 0, "ouverts": 0, "clotures": 0, "by_type": {}, "sans_verification_conflit": 0, "conflits_detectes": 0}


@router.get("/{dossier_id}")
async def get_dossier(dossier_id: str, user=Depends(get_current_user)):
    try:
        result = supabase.table("dossiers").select("*").eq("id", dossier_id).execute()
        if not result.data:
            raise HTTPException(404, "Dossier introuvable")
        return _to_api(result.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/{dossier_id}")
async def update_dossier(dossier_id: str, body: DossierUpdate, user=Depends(get_current_user)):
    try:
        raw = {k: v for k, v in body.model_dump().items() if v is not None}
        if "date_cloture" in raw:
            raw["date_cloture"] = str(raw["date_cloture"])
        data = _to_db(raw)
        if not data:
            return {"message": "Rien a mettre a jour"}
        result = supabase.table("dossiers").update(data).eq("id", dossier_id).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{dossier_id}")
async def delete_dossier(dossier_id: str, user=Depends(get_current_user)):
    try:
        supabase.table("dossiers").delete().eq("id", dossier_id).execute()
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(500, str(e))
