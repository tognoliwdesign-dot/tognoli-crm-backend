"""LEXARYS — Routes Administration"""
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
    result = supabase.table("users").select("id,email,full_name,role,barreau,is_active,lead_limit,subscription_status,created_at").execute()
    return result.data or []


@router.post("/users")
async def create_user(body: UserCreate, user=Depends(require_admin)):
    existing = supabase.table("users").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(400, "Email déjà utilisé")
    data = {
        "email": body.email,
        "password_hash": hash_password(body.password),
        "full_name": body.full_name,
        "role": body.role or "avocat",
        "barreau": body.barreau,
        "specialites": body.specialites or [],
        "is_active": True,
        "lead_limit": 500,
        "subscription_status": "trial",
    }
    result = supabase.table("users").insert(data).execute()
    return result.data[0] if result.data else {}


@router.put("/users/{user_id}")
async def update_user(user_id: str, body: dict, admin=Depends(require_admin)):
    allowed = {"full_name", "role", "barreau", "email", "is_active", "lead_limit", "subscription_status"}
    data = {k: v for k, v in body.items() if k in allowed and v is not None}
    if "password" in body:
        data["password_hash"] = hash_password(body["password"])
    result = supabase.table("users").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: dict, admin=Depends(require_admin)):
    """Alias PATCH pour mise à jour partielle (is_active, role, etc.)."""
    allowed = {"full_name", "role", "barreau", "email", "is_active", "lead_limit", "subscription_status"}
    data = {k: v for k, v in body.items() if k in allowed}
    if not data:
        raise HTTPException(400, "Aucun champ valide à mettre à jour")
    result = supabase.table("users").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


@router.post("/create-user")
async def create_user_alias(body: UserCreate, admin=Depends(require_admin)):
    """Alias pour POST /admin/users (compatibilité frontend)."""
    existing = supabase.table("users").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(400, "Email déjà utilisé")
    data = {
        "email": body.email,
        "password_hash": hash_password(body.password),
        "full_name": body.full_name,
        "role": body.role or "avocat",
        "barreau": body.barreau,
        "specialites": body.specialites or [],
        "is_active": True,
        "lead_limit": 500,
        "subscription_status": "trial",
    }
    result = supabase.table("users").insert(data).execute()
    return result.data[0] if result.data else {}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, body: dict, admin=Depends(require_admin)):
    """Réinitialise le mot de passe d'un utilisateur (admin uniquement)."""
    new_password = body.get("new_password", "")
    if len(new_password) < 8:
        raise HTTPException(400, "Le mot de passe doit contenir au moins 8 caractères")
    supabase.table("users").update({"password_hash": hash_password(new_password)}).eq("id", user_id).execute()
    return {"success": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Impossible de supprimer son propre compte")
    supabase.table("users").delete().eq("id", user_id).execute()
    return {"deleted": True}
