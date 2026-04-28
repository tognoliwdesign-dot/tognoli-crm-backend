from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user
from database import get_admin_client
from models import AIMessageRequest, AIScoreRequest, AIFollowupRequest
from services.ai_service import generate_cold_email, generate_followup, score_lead, generate_linkedin_message
from datetime import datetime

router = APIRouter()

def _get_lead(lead_id: str, user_id: str) -> dict:
    db = get_admin_client()
    result = db.table("leads").select("*").eq("id", lead_id).eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return result.data

def _save_ai_action(lead_id: str, user_id: str, action_type: str, result: str):
    db = get_admin_client()
    db.table("ai_actions").insert({"lead_id": lead_id, "user_id": user_id, "action_type": action_type, "result": result, "created_at": datetime.utcnow().isoformat()}).execute()

@router.post("/generate-message")
async def generate_message(body: AIMessageRequest, current_user: dict = Depends(get_current_user)):
    lead = _get_lead(body.lead_id, current_user["id"])
    if body.message_type == "linkedin":
        result = await generate_linkedin_message(lead)
    else:
        result = await generate_cold_email(lead, body.tone, body.language)
    _save_ai_action(body.lead_id, current_user["id"], "message", result)
    return {"message": result, "lead_id": body.lead_id, "type": body.message_type}

@router.post("/score")
async def score_lead_endpoint(body: AIScoreRequest, current_user: dict = Depends(get_current_user)):
    lead = _get_lead(body.lead_id, current_user["id"])
    score_result = await score_lead(lead)
    db = get_admin_client()
    db.table("leads").update({"score": score_result.get("score", 50), "updated_at": datetime.utcnow().isoformat()}).eq("id", body.lead_id).execute()
    _save_ai_action(body.lead_id, current_user["id"], "scoring", str(score_result))
    return score_result

@router.post("/followup")
async def generate_followup_endpoint(body: AIFollowupRequest, current_user: dict = Depends(get_current_user)):
    lead = _get_lead(body.lead_id, current_user["id"])
    result = await generate_followup(lead, body.days_since_contact)
    _save_ai_action(body.lead_id, current_user["id"], "followup", result)
    return {"message": result, "lead_id": body.lead_id}

@router.get("/history/{lead_id}")
async def get_ai_history(lead_id: str, current_user: dict = Depends(get_current_user)):
    _get_lead(lead_id, current_user["id"])
    db = get_admin_client()
    result = db.table("ai_actions").select("*").eq("lead_id", lead_id).order("created_at", desc=True).execute()
    return result.data or []
