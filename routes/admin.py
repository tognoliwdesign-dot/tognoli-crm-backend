"""
LEXARYS — Routes Administration
RBAC : gestion des permissions par fonctionnalité par utilisateur.
Les permissions sont stockées dans users.features_enabled (JSON array).
Si absent → toutes les fonctionnalités sont activées (rétrocompat).
"""
from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from auth import get_current_user, hash_password
from models import UserCreate

router = APIRouter(prefix="/admin", tags=["admin"])

# ── Fonctionnalités disponibles ────────────────────────────────────────────────
ALL_FEATURES = [
    {"slug": "dashboard",  "label": "Tableau de bord",        "icon": "◉", "description": "Vue d'ensemble du cabinet"},
    {"slug": "prospects",  "label": "Prospects",               "icon": "◈", "description": "Liste, recherche et scoring des prospects"},
    {"slug": "scraping",   "label": "Recherche de prospects",  "icon": "🔍", "description": "Scraping Sirene / BODACC / Pappers — import automatique"},
    {"slug": "clients",    "label": "Clients",                 "icon": "◎", "description": "Gestion du portefeuille clients"},
    {"slug": "dossiers",   "label": "Dossiers",                "icon": "▣", "description": "Suivi des affaires et missions"},
    {"slug": "conflicts",  "label": "Conflits d'intérêts",    "icon": "⚑", "description": "Détection et journal des conflits (RIN Art. 4)"},
    {"slug": "admin",      "label": "Administration",          "icon": "⚙", "description": "Gestion des utilisateurs et permissions"},
]
ALL_FEATURE_SLUGS = [f["slug"] for f in ALL_FEATURES]


def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Accès réservé à l'administrateur du cabinet")
    return user


def require_feature(feature: str):
    """Dependency factory — vérifie que l'user a accès à la feature."""
    async def check(user=Depends(get_current_user)):
        if user.get("role") == "admin":
            return user  # l'admin a toujours accès à tout
        enabled = user.get("features_enabled")
        if enabled is None:
            return user  # pas de restriction configurée → tout activé
        if feature not in (enabled or []):
            raise HTTPException(403, f"Fonctionnalité '{feature}' non activée pour votre compte")
        return user
    return check


# ── Endpoints permissions ──────────────────────────────────────────────────────

@router.get("/features")
async def list_features(user=Depends(get_current_user)):
    """Liste toutes les fonctionnalités disponibles."""
    return ALL_FEATURES


@router.get("/users/{user_id}/permissions")
async def get_user_permissions(user_id: str, admin=Depends(require_admin)):
    """Récupère les features activées pour un utilisateur."""
    res = supabase.table("users").select("id,email,full_name,role,features_enabled").eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(404, "Utilisateur non trouvé")
    row = res.data[0] if isinstance(res.data, list) else res.data
    enabled = row.get("features_enabled")
    return {
        "user_id": user_id,
        "features_enabled": enabled if enabled is not None else ALL_FEATURE_SLUGS,
        "all_features": ALL_FEATURES,
    }


@router.put("/users/{user_id}/permissions")
async def update_user_permissions(user_id: str, body: dict, admin=Depends(require_admin)):
    """
    Met à jour les features activées pour un utilisateur.
    body: { "features_enabled": ["dashboard", "prospects", ...] }
    """
    if user_id == admin["id"]:
        raise HTTPException(400, "Impossible de modifier ses propres permissions")
    features = body.get("features_enabled", ALL_FEATURE_SLUGS)
    # Valider que tous les slugs sont connus
    unknown = [f for f in features if f not in ALL_FEATURE_SLUGS]
    if unknown:
        raise HTTPException(400, f"Fonctionnalités inconnues : {unknown}")
    supabase.table("users").update({"features_enabled": features}).eq("id", user_id).execute()
    return {"success": True, "features_enabled": features}


@router.get("/me/permissions")
async def my_permissions(user=Depends(get_current_user)):
    """Retourne les features activées pour l'utilisateur connecté."""
    if user.get("role") == "admin":
        return {"features_enabled": ALL_FEATURE_SLUGS, "is_admin": True}
    enabled = user.get("features_enabled")
    return {
        "features_enabled": enabled if enabled is not None else ALL_FEATURE_SLUGS,
        "is_admin": False,
    }


# ── Gestion utilisateurs ───────────────────────────────────────────────────────

@router.get("/users")
async def list_users(user=Depends(require_admin)):
    result = supabase.table("users").select(
        "id,email,full_name,role,barreau,is_active,lead_limit,subscription_status,features_enabled,created_at"
    ).execute()
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
        "features_enabled": ALL_FEATURE_SLUGS,  # tout activé par défaut
    }
    result = supabase.table("users").insert(data).execute()
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
        "features_enabled": ALL_FEATURE_SLUGS,
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
    """Alias PATCH pour mise à jour partielle."""
    allowed = {"full_name", "role", "barreau", "email", "is_active", "lead_limit", "subscription_status"}
    data = {k: v for k, v in body.items() if k in allowed}
    if not data:
        raise HTTPException(400, "Aucun champ valide à mettre à jour")
    result = supabase.table("users").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, body: dict, admin=Depends(require_admin)):
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
