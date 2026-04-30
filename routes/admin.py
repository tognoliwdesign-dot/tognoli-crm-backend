"""LEXARYS - Routes Administration"""
from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from auth import get_current_user, hash_password
from models import UserCreate

router = APIRouter(prefix="/admin", tags=["admin"])

def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Accès réservé à l'administrateur du cabinet")
    return user

@router.get("/users")
async def list_users(user=Depends(require_admin)):
    result = supabase.table("users").select("id,email,first_name,last_name,role,barreau,created_at").execute()
    return result.data or []

@router.post("/users")
async def create_user(body: UserCreate, user=Depends(require_admin)):
    existing = supabase.table("users").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(400, "Email déjà utilisé")
    data = {
        "email": body.email,
        "password_hash": hash_password(body.password),
        "first_name": body.first_name,
        "last_name": body.last_name,
        "role": body.role or "avocat",
        "barreau": body.barreau,
    }
    result = supabase.table("users").insert(data).execute()
    return result.data[0] if result.data else {}

@router.put("/users/{user_id}")
async def update_user(user_id: str, body: dict, admin=Depends(require_admin)):
    allowed = {"first_name", "last_name", "role", "barreau", "email"}
    data = {k: v for k, v in body.items() if k in allowed and v is not None}
    if "password" in body:
        data["password_hash"] = hash_password(body["password"])
    result = supabase.table("users").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Impossible de supprimer son propre compte")
    supabase.table("users").delete().eq("id", user_id).execute()
    return {"deleted": True}
