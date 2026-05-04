"""LEXARYS - Routes Dossiers"""
from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from models import DossierCreate, DossierUpdate
from auth import get_current_user


router = APIRouter(prefix="/dossiers", tags=["dossiers"])


@router.get("")
async def list_dossiers(status: str = None, search: str = None, limit: int = 200, user=Depends(get_current_user)):
    q = supabase.table("dossiers").select("*").eq("user_id", user["id"])
    if status: q = q.eq("status", status)
    if search: q = q.or_(f"title.ilike.%{search}%,reference.ilike.%{search}%,partie_adverse_name.ilike.%{search}%")
    q = q.order("created_at", desc=True).limit(limit)
    return q.execute().data or []


@router.post("")
async def create_dossier(body: DossierCreate, user=Depends(get_current_user)):
    data = body.dict()
    data["user_id"] = user["id"]
    for field in ["date_ouverture", "date_cloture"]:
        if data.get(field): data[field] = str(data[field])
    result = supabase.table("dossiers").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Erreur creation dossier")
    return result.data[0]


@router.get("/{dossier_id}")
async def get_dossier(dossier_id: int, user=Depends(get_current_user)):
    result = supabase.table("dossiers").select("*").eq("id", dossier_id).eq("user_id", user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Dossier non trouve")
    return result.data[0]


@router.put("/{dossier_id}")
async def update_dossier(dossier_id: int, body: DossierUpdate, user=Depends(get_current_user)):
    existing = supabase.table("dossiers").select("id").eq("id", dossier_id).eq("user_id", user["id"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Dossier non trouve")
    data = {k: v for k, v in body.dict().items() if v is not None}
    for field in ["date_ouverture", "date_cloture"]:
        if field in data and data[field]: data[field] = str(data[field])
    result = supabase.table("dossiers").update(data).eq("id", dossier_id).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Erreur mise a jour")
    return result.data[0]


@router.delete("/{dossier_id}")
async def delete_dossier(dossier_id: int, user=Depends(get_current_user)):
    existing = supabase.table("dossiers").select("id").eq("id", dossier_id).eq("user_id", user["id"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Dossier non trouve")
    supabase.table("dossiers").delete().eq("id", dossier_id).execute()
    return {"message": "Dossier supprime"}
