import io
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from auth import get_current_user
from database import get_admin_client
from models import LeadCreate, LeadUpdate, LeadStatusUpdate
from datetime import datetime

router = APIRouter()

@router.get("")
async def list_leads(status: str = None, sector: str = None, city: str = None, search: str = None, limit: int = 100, offset: int = 0, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    query = db.table("leads").select("*, ai_actions(id, action_type, created_at)").eq("user_id", current_user["id"])
    if status: query = query.eq("status", status)
    if sector: query = query.ilike("sector", f"%{sector}%")
    if city: query = query.ilike("city", f"%{city}%")
    if search: query = query.or_(f"company_name.ilike.%{search}%,contact_name.ilike.%{search}%,email.ilike.%{search}%")
    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return result.data or []

@router.post("")
async def create_lead(body: LeadCreate, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    count_result = db.table("leads").select("id", count="exact").eq("user_id", current_user["id"]).execute()
    current_count = count_result.count or 0
    lead_limit = current_user.get("lead_limit", 100)
    if current_count >= lead_limit:
        raise HTTPException(status_code=403, detail=f"Limite de {lead_limit} leads atteinte")
    lead_data = body.dict()
    lead_data["user_id"] = current_user["id"]
    lead_data["score"] = 0
    lead_data["status"] = "new"
    result = db.table("leads").insert(lead_data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Erreur création lead")
    return result.data[0]

@router.get("/{lead_id}")
async def get_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    result = db.table("leads").select("*, ai_actions(*)").eq("id", lead_id).eq("user_id", current_user["id"]).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return result.data

@router.put("/{lead_id}")
async def update_lead(lead_id: str, body: LeadUpdate, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune modification")
    updates["updated_at"] = datetime.utcnow().isoformat()
    result = db.table("leads").update(updates).eq("id", lead_id).eq("user_id", current_user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return result.data[0]

@router.delete("/{lead_id}")
async def delete_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    db.table("ai_actions").delete().eq("lead_id", lead_id).execute()
    db.table("leads").delete().eq("id", lead_id).eq("user_id", current_user["id"]).execute()
    return {"message": "Lead supprimé"}

@router.put("/{lead_id}/status")
async def update_lead_status(lead_id: str, body: LeadStatusUpdate, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    result = db.table("leads").update({"status": body.status.value, "updated_at": datetime.utcnow().isoformat()}).eq("id", lead_id).eq("user_id", current_user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return result.data[0]

@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Fichier CSV requis")
    contents = await file.read()
    df = pd.read_csv(io.StringIO(contents.decode("utf-8")))
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
    column_map = {"entreprise": "company_name", "société": "company_name", "company": "company_name", "nom": "contact_name", "contact": "contact_name", "name": "contact_name", "mail": "email", "e-mail": "email", "téléphone": "phone", "tel": "phone", "telephone": "phone", "site": "website", "url": "website", "secteur": "sector", "industry": "sector", "ville": "city"}
    df.rename(columns=column_map, inplace=True)
    db = get_admin_client()
    count_result = db.table("leads").select("id", count="exact").eq("user_id", current_user["id"]).execute()
    available = current_user.get("lead_limit", 100) - (count_result.count or 0)
    leads_to_insert = []
    for _, row in df.head(available).iterrows():
        lead = {"user_id": current_user["id"], "company_name": str(row.get("company_name", "Inconnu")), "contact_name": str(row.get("contact_name", "")), "email": str(row.get("email", "")), "phone": str(row.get("phone", "")), "website": str(row.get("website", "")), "sector": str(row.get("sector", "")), "city": str(row.get("city", "")), "country": str(row.get("country", "France")), "notes": str(row.get("notes", "")), "score": 0, "status": "new", "source": "csv_import"}
        lead = {k: ("" if v == "nan" else v) for k, v in lead.items()}
        leads_to_insert.append(lead)
    if leads_to_insert:
        db.table("leads").insert(leads_to_insert).execute()
    return {"imported": len(leads_to_insert), "skipped": max(0, len(df) - available), "message": f"{len(leads_to_insert)} leads importés"}

@router.get("/stats/pipeline")
async def get_pipeline_stats(current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    result = db.table("leads").select("status, score").eq("user_id", current_user["id"]).execute()
    leads = result.data or []
    pipeline = {"new": 0, "contacted": 0, "qualified": 0, "proposal": 0, "won": 0, "lost": 0}
    scores = [l["score"] for l in leads if l.get("score")]
    for lead in leads:
        s = lead.get("status", "new")
        pipeline[s] = pipeline.get(s, 0) + 1
    return {"pipeline": pipeline, "total": len(leads), "avg_score": round(sum(scores) / len(scores), 1) if scores else 0, "won_rate": round((pipeline["won"] / len(leads)) * 100, 1) if leads else 0}
