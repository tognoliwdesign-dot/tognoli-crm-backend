"""LEXARYS - Routes Dossiers"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, date
from database import supabase
from models import DossierCreate, DossierUpdate
from auth import get_current_user
import random, string

router = APIRouter(prefix="/dossiers", tags=["dossiers"])

def _generate_reference():
    year = datetime.now().year
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"LEX-{year}-{suffix}"

@router.get("")
async def list_dossiers(status: str = None, client_id: str = None, limit: int = 100, user=Depends(get_current_user)):
    q = supabase.table("dossiers").select("*, clients(company_name, last_name, first_name)")
    if status: q = q.eq("status", status)
    if client_id: q = q.eq("client_id", client_id)
    q = q.order("created_at", desc=True).limit(limit)
    return q.execute().data or []

@router.post("")
async def create_dossier(body: DossierCreate, user=Depends(get_current_user)):
    data = body.dict()
    data["avocat_id"] = user["id"]
    data["reference"] = data.get("reference") or _generate_reference()
    if data.get("date_ouverture"):
        data["date_ouverture"] = str(data["date_ouverture"])
    result = supabase.table("dossiers").insert(data).execute()
    return result.data[0] if result.data else {}

@router.get("/stats")
async def dossier_stats(user=Depends(get_current_user)):
    all_d = supabase.table("dossiers").select("status,type_dossier,conflict_check_done,conflict_check_result").execute()
    data = all_d.data or []
    return {
        "total": len(data),
        "ouverts": sum(1 for d in data if d.get("status") == "ouvert"),
        "clotures": sum(1 for d in data if d.get("status") == "cloture"),
        "sans_verification_conflit": sum(1 for d in data if not d.get("conflict_check_done")),
        "conflits_detectes": sum(1 for d in data if d.get("conflict_check_result") in ("orange", "rouge")),
        "by_type": {t: sum(1 for d in data if d.get("type_dossier") == t) for t in ["contentieux", "conseil", "negociation", "arbitrage"]},
    }

@router.get("/{dossier_id}")
async def get_dossier(dossier_id: str, user=Depends(get_current_user)):
    result = supabase.table("dossiers").select("*, clients(*)").eq("id", dossier_id).single().execute()
    if not result.data: raise HTTPException(404, "Dossier introuvable")
    return result.data

@router.put("/{dossier_id}")
async def update_dossier(dossier_id: str, body: DossierUpdate, user=Depends(get_current_user)):
    data = {k: v for k, v in body.dict().items() if v is not None}
    if "date_cloture" in data:
        data["date_cloture"] = str(data["date_cloture"])
    if "date_ouverture" in data:
        data["date_ouverture"] = str(data["date_ouverture"])
    result = supabase.table("dossiers").update(data).eq("id", dossier_id).execute()
    return result.data[0] if result.data else {}

@router.put("/{dossier_id}/conflict-check")
async def mark_conflict_checked(dossier_id: str, check_result: str = "vert", user=Depends(get_current_user)):
    result = supabase.table("dossiers").update({
        "conflict_check_done": True,
        "conflict_check_date": datetime.utcnow().isoformat(),
        "conflict_check_result": check_result,
    }).eq("id", dossier_id).execute()
    return result.data[0] if result.data else {}

@router.delete("/{dossier_id}")
async def delete_dossier(dossier_id: str, user=Depends(get_current_user)):
    supabase.table("dossiers").delete().eq("id", dossier_id).execute()
    return {"deleted": True}
-
