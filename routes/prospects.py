"""LEXARYS — Routes Prospects"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, date
from database import supabase
from models import ProspectCreate, ProspectUpdate, ProspectStatusUpdate
from auth import get_current_user
from scoring import ProspectData, score_prospect, score_to_dict

router = APIRouter(prefix="/prospects", tags=["prospects"])

def _build_score(p):
    dc = p.get("date_creation")
    data = ProspectData(
        company_name=p.get("company_name",""),
        naf_code=p.get("naf_code"),
        effectif_tranche=p.get("effectif_tranche"),
        forme_juridique=p.get("forme_juridique"),
        date_creation=date.fromisoformat(dc) if dc else None,
        capital_social=p.get("capital_social"),
        bodacc_procedure=p.get("bodacc_procedure"),
        is_international=p.get("is_international",False),
        is_multi_site=p.get("is_multi_site",False),
        has_litigation_history=p.get("has_litigation_history",False),
        nb_contacts=p.get("nb_contacts",0),
        has_formal_refusal=p.get("has_formal_refusal",False),
        has_consent=p.get("consent_obtained",False),
    )
    return score_to_dict(score_prospect(data))

@router.get("")
async def list_prospects(status: str=None, search: str=None, limit: int=200, user=Depends(get_current_user)):
    q = supabase.table("prospects").select("*")
    if status: q = q.eq("status", status)
    if search: q = q.ilike("company_name", f"%{search}%")
    q = q.order("score", desc=True).limit(limit)
    return q.execute().data or []

@router.post("")
async def create_prospect(body: ProspectCreate, user=Depends(get_current_user)):
    data = body.dict()
    data["user_id"] = user["id"]
    if data.get("date_creation"): data["date_creation"] = str(data["date_creation"])
    sr = _build_score(data)
    data["score"] = sr["total"]
    data["score_breakdown"] = sr["breakdown"]
    data["score_updated_at"] = datetime.utcnow().isoformat()
    data["deonto_alert"] = sr.get("deonto_alert", False)
    result = supabase.table("prospects").insert(data).execute()
    return result.data[0] if result.data else {}

@router.get("/stats")
async def prospect_stats(user=Depends(get_current_user)):
    all_p = supabase.table("prospects").select("*").execute()
    data = all_p.data or []
    pipeline = {}
    for p in data:
        s = p.get("status","nouveau")
        pipeline[s] = pipeline.get(s,0)+1
    scores = [p["score"] for p in data if p.get("score",0)>0]
    return {
        "total": len(data),
        "by_status": pipeline,
        "avg_score": round(sum(scores)/len(scores),1) if scores else 0,
        "deonto_alerts": sum(1 for p in data if p.get("deonto_alert") or p.get("has_formal_refusal")),
        "converted": pipeline.get("converti",0),
    }

@router.get("/{prospect_id}")
async def get_prospect(prospect_id: str, user=Depends(get_current_user)):
    result = supabase.table("prospects").select("*").eq("id", prospect_id).single().execute()
    if not result.data: raise HTTPException(404, "Prospect introuvable")
    return result.data

@router.put("/{prospect_id}")
async def update_prospect(prospect_id: str, body: ProspectUpdate, user=Depends(get_current_user)):
    data = {k: v for k,v in body.dict().items() if v is not None}
    data["updated_at"] = datetime.utcnow().isoformat()
    result = supabase.table("prospects").update(data).eq("id", prospect_id).execute()
    return result.data[0] if result.data else {}

@router.post("/{prospect_id}/rescore")
async def rescore_prospect(prospect_id: str, user=Depends(get_current_user)):
    ex = supabase.table("prospects").select("*").eq("id", prospect_id).single().execute()
    if not ex.data: raise HTTPException(404, "Prospect introuvable")
    sr = _build_score(ex.data)
    upd = {"score": sr["total"], "score_breakdown": sr["breakdown"], "score_updated_at": datetime.utcnow().isoformat(), "deonto_alert": sr.get("deonto_alert",False), "updated_at": datetime.utcnow().isoformat()}
    result = supabase.table("prospects").update(upd).eq("id", prospect_id).execute()
    return {**(result.data[0] if result.data else {}), "score_detail": sr}

@router.post("/{prospect_id}/contact")
async def log_contact(prospect_id: str, body: dict, user=Depends(get_current_user)):
    ex = supabase.table("prospects").select("nb_contacts,has_formal_refusal").eq("id", prospect_id).single().execute()
    if not ex.data: raise HTTPException(404, "Prospect introuvable")
    if ex.data.get("has_formal_refusal"): raise HTTPException(403, "Prospection bloquée — refus formel enregistré")
    supabase.table("prospect_contacts").insert({"prospect_id": prospect_id, "user_id": user["id"], "contact_mode": body.get("contact_mode","email"), "contact_date": datetime.utcnow().isoformat()}).execute()
    new_count = (ex.data.get("nb_contacts") or 0)+1
    supabase.table("prospects").update({"nb_contacts": new_count, "last_contact_at": datetime.utcnow().isoformat(), "updated_at": datetime.utcnow().isoformat()}).eq("id", prospect_id).execute()
    return {"nb_contacts": new_count}

@router.delete("/{prospect_id}")
async def delete_prospect(prospect_id: str, user=Depends(get_current_user)):
    supabase.table("prospects").delete().eq("id", prospect_id).execute()
    return {"deleted": True}
