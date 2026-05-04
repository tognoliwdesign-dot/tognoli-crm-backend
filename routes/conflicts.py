"""LEXARYS - Routes Conflits d'Interets (Art. 4 RIN)"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ConflictCheckRequest, ConflictDecision
from auth import get_current_user
from conflict_engine import ConflictEngine, EntityToCheck, RegisteredEntity, conflict_result_to_dict

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

def _load_cabinet_entities(user_id: str):
    entities = []
    # Filtre obligatoire par user_id (isolation multi-tenant RIN Art. 4)
    clients = supabase.table("clients").select("id,company_name,last_name,first_name,siren,siret,status").eq("user_id", user_id).execute()
    for c in (clients.data or []):
        name = c.get("company_name") or f"{c.get('last_name','')} {c.get('first_name','')}".strip()
        if not name: continue
        entity_type = "client_actuel" if c.get("status") == "actif" else "client_ancien"
        entities.append(RegisteredEntity(id=c["id"], name=name, entity_type=entity_type, siren=c.get("siren"), siret=c.get("siret")))
    dossiers = supabase.table("dossiers").select("id,partie_adverse_name,partie_adverse_siren").eq("user_id", user_id).execute()
    for d in (dossiers.data or []):
        name = d.get("partie_adverse_name", "")
        if not name: continue
        entities.append(RegisteredEntity(id=d["id"], name=name, entity_type="partie_adverse", siren=d.get("partie_adverse_siren")))
    return entities

@router.post("/check")
async def check_conflict(req: ConflictCheckRequest, user=Depends(get_current_user)):
    entities = _load_cabinet_entities(user["id"])
    engine = ConflictEngine(entities)
    to_check = EntityToCheck(
        name=req.entity_name,
        siren=req.siren,
        siret=req.siret,
        entity_type=req.entity_type or "unknown"
    )
    result = engine.check(to_check)
    result_dict = conflict_result_to_dict(result)
    # Enregistrer la verification en base
    supabase.table("conflict_checks").insert({
        "checked_by": user["id"],
        "checked_entity_name": req.entity_name,
        "checked_entity_siren": req.siren,
        "checked_entity_siret": req.siret,
        "checked_entity_type": req.entity_type or "unknown",
        "result": result_dict.get("verdict", "clear"),
        "conflicts_found": len(result_dict.get("conflicts", [])),
        "checked_at": datetime.utcnow().isoformat()
    }).execute()
    return result_dict

@router.get("/history")
async def conflict_history(user=Depends(get_current_user)):
    rows = supabase.table("conflict_checks").select("*").eq("checked_by", user["id"]).order("checked_at", desc=True).limit(50).execute()
    return rows.data or []

@router.put("/decision")
async def record_decision(dec: ConflictDecision, user=Depends(get_current_user)):
    supabase.table("conflict_checks").update({
        "decision": dec.decision,
        "decision_notes": dec.notes,
        "decision_at": datetime.utcnow().isoformat()
    }).eq("id", dec.check_id).eq("checked_by", user["id"]).execute()
    return {"ok": True}

@router.get("/stats")
async def conflict_stats(user=Depends(get_current_user)):
    rows = supabase.table("conflict_checks").select("result,decision").eq("checked_by", user["id"]).execute()
    data = rows.data or []
    total = len(data)
    blocked = sum(1 for r in data if r.get("result") in ("blocked", "conflict"))
    clear = sum(1 for r in data if r.get("result") == "clear")
    pending = sum(1 for r in data if not r.get("decision"))
    return {"total": total, "blocked": blocked, "clear": clear, "pending_decision": pending}
