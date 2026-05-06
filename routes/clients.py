"""LEXARYS -- Routes Clients (schema DB reel)"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ClientCreate, ClientUpdate
from auth import get_current_user

router = APIRouter(prefix="/clients", tags=["clients"])

CLIENT_COLUMNS = {
    'user_id', 'prospect_id', 'raison_sociale', 'siren', 'siret',
    'forme_juridique', 'email', 'phone', 'adresse', 'ville',
    'status', 'statut', 'notes', 'is_confidential', 'created_at',
}

API_TO_DB = {
    'company_name':  'raison_sociale',
    'last_name':     'raison_sociale',
    'address':       'adresse',
    'city':          'ville',
    'client_type':   None,
    'first_name':    None,
    'since_date':    None,
    'end_date':      None,
    'postal_code':   None,
    'country':       None,
}


def _to_db(data: dict) -> dict:
    result = {}
    if data.get('company_name'):
        result['raison_sociale'] = data['company_name']
    elif data.get('last_name'):
        first = data.get('first_name', '')
        result['raison_sociale'] = f"{data['last_name']} {first}".strip()

    for k, v in data.items():
        if k in ('company_name', 'last_name', 'first_name', 'client_type'):
            continue
        db_key = API_TO_DB.get(k, k)
        if db_key is None:
            continue
        if v is not None:
            result[db_key] = v

    return {k: v for k, v in result.items() if k in CLIENT_COLUMNS and v is not None}


def _to_api(row: dict) -> dict:
    if not row:
        return row
    r = dict(row)
    if 'raison_sociale' in r:
        r['company_name'] = r['raison_sociale']
    if 'adresse' in r:
        r['address'] = r['adresse']
    if 'ville' in r:
        r['city'] = r['ville']
    return r


@router.get("")
async def list_clients(status: str = None, search: str = None, limit: int = 200, user=Depends(get_current_user)):
    try:
        q = supabase.table("clients").select("*")
        if status:
            q = q.eq("status", status)
        if search:
            q = q.ilike("raison_sociale", f"%{search}%")
        q = q.order("created_at", desc=True).limit(limit)
        rows = q.execute().data or []
        return [_to_api(r) for r in rows]
    except Exception as e:
        raise HTTPException(500, f"Erreur liste clients: {str(e)}")


@router.post("")
async def create_client(body: ClientCreate, user=Depends(get_current_user)):
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ClientCreate, ClientUpdate
from auth import get_current_user

router = APIRouter(prefix="/clients", tags=["clients"])

CLIENT_COLUMNS = {
    'user_id', 'prospect_id', 'raison_sociale', 'siren', 'siret',
    'forme_juridique', 'email', 'phone', 'adresse', 'ville',
    'status', 'statut', 'notes', 'is_confidential', 'created_at',
}

API_TO_DB = {
    'company_name':  'raison_sociale',
    'last_name':     'raison_sociale',
    'address':       'adresse',
    'city':          'ville',
    'client_type':   None,
    'first_name':    None,
    'since_date':    None,
    'end_date':      None,
    'postal_code':   None,
    'country':       None,
}


def _to_db(data: dict) -> dict:
    result = {}
    if data.get('company_name'):
        result['raison_sociale'] = data['company_name']
    elif data.get('last_name'):
        first = data.get('first_name', '')
        result['raison_sociale'] = f"{data['last_name']} {first}".strip()
    for k, v in data.items():
        if k in ('company_name', 'last_name', 'first_name', 'client_type'):
            continue
        db_key = API_TO_DB.get(k, k)
        if db_key is None:
            continue
        if v is not None:
            result[db_key] = v
    return {k: v for k, v in result.items() if k in CLIENT_COLUMNS and v is not None}


def _to_api(row: dict) -> dict:
    if not row:
        return row
    r = dict(row)
    if 'raison_sociale' in r:
        r['company_name'] = r['raison_sociale']
    if 'adresse' in r:
        r['address'] = r['adresse']
    if 'ville' in r:
        r['city'] = r['ville']
    return r


@router.get("")
async def list_clients(status: str = None, search: str = None, limit: int = 200, user=Depends(get_current_user)):
    try:
        q = supabase.table("clients").select("*")
        if status:
            q = q.eq("status", status)
        if search:
            q = q.ilike("raison_sociale", f"%{search}%")
        q = q.order("created_at", desc=True).limit(limit)
        rows = q.execute().data or []
        return [_to_api(r) for r in rows]
    except Exception as e:
        raise HTTPException(500, f"Erreur liste clients: {str(e)}")


@router.post("")
async def create_client(body: ClientCreate, user=Depends(get_current_user)):
    try:
        raw = body.model_dump()
        raw["user_id"] = user["id"]
        data = _to_db(raw)
        if not data.get("raison_sociale"):
            raise HTTPException(400, "Nom du client requis (company_name ou last_name)")
        result = supabase.table("clients").insert(data).execute()
        return _to_api(result.data[0]) if result.data else {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur creation client: {str(e)}")


@router.get("/{client_id}")
async def get_client(client_id: str, user=Depends(get_current_user)):
    try:
        result = supabase.table("clients").select("*").eq("id", client_id).execute()
        if not result.data:
            raise HTTPException(404, "Client introuvable")
        client = _to_api(result.data[0])
        try:
            dossiers = supabase.table("dossiers").select("*").eq("client_id", client_id).execute()
            client["dossiers"] = dossiers.data or []
        except Exception:
            client["dossiers"] = []
        return client
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, user=Depends(get_current_user)):
    try:
        raw = {k: v for k, v in body.model_dump().items() if v is not None}
        data = _to_db(raw)
        if not data:
            return {"message": "Rien a mettre a jour"}
        result = supabase.table("clients").update(data).eq("id", client_id).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{client_id}")
async def delete_client(client_id: str, user=Depends(get_current_user)):
    try:
        supabase.table("clients").delete().eq("id", client_id).execute()
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(500, str(e))
