"""LEXARYS - Routes Dossiers"""
from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from models import DossierCreate, DossierUpdate
from auth import get_current_user

router = APIRouter(prefix="/dossiers", tags=["dossiers"])

# Colonnes valides de la table dossiers
DOSSIER_COLUMNS = {
    'reference', 'client_id', 'avocat_id', 'type_dossier', 'matiere',
    'juridiction', 'partie_adverse_name', 'partie_adverse_siret',
    'status', 'date_ouverture', 'date_cloture', 'description',
    'conflict_check_done', 'conflict_check_date', 'conflict_check_result'
}


def _prepare_dossier_data(data: dict) -> dict:
    """Traduit les noms de champs modele -> colonnes DB et filtre les colonnes inconnues."""
    # Renommage frontend -> DB
    if 'partie_adverse' in data:
        data['partie_adverse_name'] = data.pop('partie_adverse')
    if 'partie_adverse_siren' in data:
        data['partie_adverse_siret'] = data.pop('partie_adverse_siren')
    if 'notes' in data and not data.get('description'):
        data['description'] = data.pop('notes')
    # Filtre uniquement les colonnes existantes
    return {k: v for k, v in data.items() if k in DOSSIER_COLUMNS}


@router.get("")
async def list_dossiers(status: str = None, search: str = None, limit: int = 200, user=Depends(get_current_user)):
    q = supabase.table("dossiers").select("*").eq("avocat_id", user["id"])
    if status: q = q.eq("status", status)
    if search: q = q.or_(f"reference.ilike.%{search}%,partie_adverse_name.ilike.%{search}%")
    q = q.order("created_at", desc=True).limit(limit)
    return q.execute().data or []


@router.post("")
async def create_dossier(body: DossierCreate, user=Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    data = _prepare_dossier_data(data)
    data["avocat_id"] = user["id"]
    for field in ["date_ouverture", "date_cloture"]:
        if data.get(field): data[field] = str(data[field])
    result = supabase.table("dossiers").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Erreur creation dossier")
    return result.data[0]


@router.get("/{dossier_id}")
async def get_dossier(dossier_id: str, user=Depends(get_current_user)):
    result = supabase.table("dossiers").select("*").eq("id", dossier_id).eq("avocat_id", user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Dossier non trouve")
    return result.data[0]


@router.put("/{dossier_id}")
async def update_dossier(dossier_id: str, body: DossierUpdate, user=Depends(get_current_user)):
    existing = supabase.table("dossiers").select("id").eq("id", dossier_id).eq("avocat_id", user["id"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Dossier non trouve")
    data = body.model_dump(exclude_none=True)
    data = _prepare_dossier_data(data)
    for field in ["date_ouverture", "date_cloture"]:
        if data.get(field): data[field] = str(data[field])
    result = supabase.table("dossiers").update(data).eq("id", dossier_id).execute()
    return result.data[0] if result.data else {}


@router.delete("/{dossier_id}")
async def delete_dossier(dossier_id: str, user=Depends(get_current_user)):
    existing = supabase.table("dossiers").select("id").eq("id", dossier_id).eq("avocat_id", user["id"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Dossier non trouve")
    supabase.table("dossiers").delete().eq("id", dossier_id).execute()
    return {"deleted": True}
