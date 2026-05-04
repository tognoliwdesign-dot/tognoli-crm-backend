"""LEXARYS - Routes Clients"""
from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from models import ClientCreate, ClientUpdate
from auth import get_current_user


router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("")
async def list_clients(status: str = None, search: str = None, limit: int = 200, user=Depends(get_current_user)):
    q = supabase.table("clients").select("*").eq("user_id", user["id"])
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
    if not result.data:
        raise HTTPException(status_code=400, detail="Erreur creation client")
    return result.data[0]


@router.get("/{client_id}")
async def get_client(client_id: int, user=Depends(get_current_user)):
    result = supabase.table("clients").select("*").eq("id", client_id).eq("user_id", user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Client non trouve")
    return result.data[0]


@router.put("/{client_id}")
async def update_client(client_id: int, body: ClientUpdate, user=Depends(get_current_user)):
    existing = supabase.table("clients").select("id").eq("id", client_id).eq("user_id", user["id"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Client non trouve")
    data = {k: v for k, v in body.dict().items() if v is not None}
    if "since_date" in data and data["since_date"]: data["since_date"] = str(data["since_date"])
    result = supabase.table("clients").update(data).eq("id", client_id).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Erreur mise a jour")
    return result.data[0]


@router.delete("/{client_id}")
async def delete_client(client_id: int, user=Depends(get_current_user)):
    existing = supabase.table("clients").select("id").eq("id", client_id).eq("user_id", user["id"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Client non trouve")
    supabase.table("clients").delete().eq("id", client_id).execute()
    return {"message": "Client supprime"}
