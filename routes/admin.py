from fastapi import APIRouter, Depends, HTTPException
from auth import require_admin, hash_password
from database import get_admin_client
from models import UserCreate, UserUpdate
from datetime import datetime, date

router = APIRouter()

@router.get("/stats")
async def get_admin_stats(admin=Depends(require_admin)):
    db = get_admin_client()
    users = db.table("users").select("*").eq("role", "client").execute()
    leads = db.table("leads").select("id, created_at, status").execute()
    emails = db.table("email_logs").select("id, status, sent_at").execute()
    subs = db.table("subscriptions").select("*").eq("status", "active").execute()
    total_users = len(users.data) if users.data else 0
    total_leads = len(leads.data) if leads.data else 0
    total_emails = len([e for e in (emails.data or []) if e.get("status") == "sent"])
    active_subs = len(subs.data) if subs.data else 0
    revenue = active_subs * 49
    return {"total_users": total_users, "total_leads": total_leads, "total_emails_sent": total_emails, "active_subscriptions": active_subs, "estimated_revenue_eur": revenue, "leads_by_status": _count_by_field(leads.data or [], "status")}

@router.get("/users")
async def list_users(admin=Depends(require_admin)):
    db = get_admin_client()
    result = db.table("users").select("id, email, role, company_name, is_active, lead_limit, subscription_status, created_at").eq("role", "client").order("created_at", desc=True).execute()
    users = result.data or []
    for user in users:
        leads = db.table("leads").select("id", count="exact").eq("user_id", user["id"]).execute()
        user["leads_count"] = leads.count or 0
    return users

@router.post("/users")
async def create_user(body: UserCreate, admin=Depends(require_admin)):
    db = get_admin_client()
    existing = db.table("users").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    new_user = {"email": body.email, "password_hash": hash_password(body.password), "company_name": body.company_name, "role": body.role.value, "lead_limit": body.lead_limit, "is_active": True, "subscription_status": "trial"}
    result = db.table("users").insert(new_user).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Erreur création utilisateur")
    user = result.data[0]
    db.table("email_config").insert({"user_id": user["id"], "daily_limit": 10, "current_warmup_day": 1, "emails_sent_today": 0}).execute()
    return {"message": "Compte créé", "user_id": user["id"]}

@router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, admin=Depends(require_admin)):
    db = get_admin_client()
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune modification")
    result = db.table("users").update(updates).eq("id", user_id).execute()
    return {"message": "Utilisateur mis à jour"}

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_admin)):
    db = get_admin_client()
    db.table("leads").delete().eq("user_id", user_id).execute()
    db.table("email_config").delete().eq("user_id", user_id).execute()
    db.table("users").delete().eq("id", user_id).execute()
    return {"message": "Utilisateur supprimé"}

@router.put("/users/{user_id}/limits")
async def set_user_limits(user_id: str, lead_limit: int, admin=Depends(require_admin)):
    db = get_admin_client()
    db.table("users").update({"lead_limit": lead_limit}).eq("id", user_id).execute()
    return {"message": f"Limite fixée à {lead_limit} leads"}

def _count_by_field(items: list, field: str) -> dict:
    counts = {}
    for item in items:
        val = item.get(field, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts
