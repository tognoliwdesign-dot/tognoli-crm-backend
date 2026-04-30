"""LEXARYS - Routes Clients"""
from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from models import ClientCreate, ClientUpdate
from auth import get_current_user

router = APIRouter(prefix="/clients", tags=["clients"])

@router.get("")
async def list_clients(status: str = None, search: str = None, limit: int = 200, user=Depends(get_current_user)):
    q = supabase.table("clients").select("*")
    if status: q = q.eq("status", status)
    if search: q = q.or_(f"company_name.ilike.%{search}%,last_name.ilike.%{search}%")
    q = q.order("created_at", desc=True).limit(limit)
    return q.execute().data or []

@router.post("")
async def create_client(body: ClientCreate, user=Depends(get_current_user)):
    data = body.dict()
    data["user_id"] = user["id"]
    if data.get("since_date"): data["since_date"] = str(data["since_date"])
    result = supabase.table("clients").insert(data).execute()
    return result.data[0] if result.data else {}

@router.get("/{client_id}")
async def get_client(client_id: str, user=Depends(get_current_user)):
    result = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not result.data: raise HTTPException(404, "Client introuvable")
    dossiers = supabase.table("dossiers").select("*").eq("client_id", client_id).execute()
    return {**result.data, "dossiers": dossiers.data or []}

@router.put("/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, user=Depends(get_current_user)):
    data = {k: v for k, v in body.dict().items() if v is not None}
    if "end_date" in data: data["end_date"] = str(data["end_date"])
    result = supabase.table("clients").update(data).eq("id", client_id).execute()
    return result.data[0] if result.data else {}

@router.delete("/{client_id}")
async def delete_client(client_id: str, user=Depends(get_current_user)):
    dossiers = supabase.table("dossiers").select("id").eq("client_id", client_id).eq("status", "ouvert").execute()
    if dossiers.data: raise HTTPException(400, "Impossible de supprimer un client avec des dossiers ouverts")
    supabase.table("clients").delete().eq("id", client_id).execute()
    return {"deleted": True}
