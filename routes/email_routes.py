from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user
from database import get_admin_client
from models import EmailSendRequest, EmailConfigUpdate
from services.email_service import send_email, get_email_config

router = APIRouter()

@router.post("/send")
async def send_email_endpoint(body: EmailSendRequest, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    lead = db.table("leads").select("*").eq("id", body.lead_id).eq("user_id", current_user["id"]).single().execute()
    if not lead.data:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    result = await send_email(user_id=current_user["id"], lead_id=body.lead_id, recipient_email=body.recipient_email, subject=body.subject, body=body.body)
    return result

@router.get("/logs")
async def get_email_logs(limit: int = 50, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    result = db.table("email_logs").select("*, leads(company_name, contact_name)").eq("user_id", current_user["id"]).order("created_at", desc=True).limit(limit).execute()
    return result.data or []

@router.get("/config")
async def get_config(current_user: dict = Depends(get_current_user)):
    return await get_email_config(current_user["id"])

@router.put("/config")
async def update_config(body: EmailConfigUpdate, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune modification")
    db.table("email_config").update(updates).eq("user_id", current_user["id"]).execute()
    return {"message": "Configuration mise à jour"}

@router.get("/stats")
async def get_email_stats(current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    result = db.table("email_logs").select("status, sent_at").eq("user_id", current_user["id"]).execute()
    logs = result.data or []
    config = await get_email_config(current_user["id"])
    return {"total_sent": len([l for l in logs if l["status"] == "sent"]), "total_failed": len([l for l in logs if l["status"] == "failed"]), "sent_today": config.get("emails_sent_today", 0), "daily_limit": config.get("daily_limit", 10), "warmup_day": config.get("current_warmup_day", 1), "remaining_today": max(0, config.get("daily_limit", 10) - config.get("emails_sent_today", 0))}
