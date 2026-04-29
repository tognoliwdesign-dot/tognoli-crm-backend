"""LEXARYS — Routes Conflits d'Intérêts (Art. 4 RIN)"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ConflictCheckRequest, ConflictDecision
from auth import get_current_user
from conflict_engine import ConflictEngine, EntityToCheck, RegisteredEntity, conflict_result_to_dict

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

def _load_cabinet_entities(user_id: str):
    entities = []
    clients = supabase.table("clients").select("id,company_name,last_name,first_name,siren,siret,status").execute()
    for c in (clients.data or []):
        name = c.get("company_name") or f"{c.get('last_name','')} {c.get('first_name','')}".strip()
        if not name: continue
        entity_type = "client_actuel" if c.get("status") == "actif" else "client_ancien"
        entities.append(RegisteredEntity(id=c["id"], name=name, entity_type=entity_type, siren=c.get("siren"), siret=c.get("siret")))
    dossiers = supabase.table("dossiers").select("id,reference,partie_adverse,partie_adverse_siren").execute()
    for d in (dossiers.data or []):
        pa = d.get("partie_adverse")
        if not pa: continue
        entities.append(RegisteredEntity(id=d["id"], name=pa, entity_type="partie_adverse", siren=d.get("partie_adverse_siren"), dossier_ref=d.get("reference")))
    return entities

@router.post("/check")
async def check_conflict(body: ConflictCheckRequest, user=Depends(get_current_user)):
    entities = _load_cabinet_entities(user["id"])
    engine = ConflictEngine(entities)
    entity = EntityToCheck(name=body.entity_name, siren=body.siren, siret=body.siret)
    result = engine.check(entity)
    result_dict = conflict_result_to_dict(result)
    saved = supabase.table("conflict_checks").insert({
        "checked_by": user["id"],
        "entity_name": body.entity_name,
        "siren": body.siren,
        "siret": body.siret,
        "entity_type": body.entity_type,
        "result": result.result,
        "matches": result_dict["conflicts"],
        "recommendation": result_dict["recommendation"],
    }).execute()
    check_id = saved.data[0]["id"] if saved.data else None
    return {**result_dict, "id": check_id}

@router.get("/history")
async def conflict_history(limit: int = 50, result: str = None, user=Depends(get_current_user)):
    q = supabase.table("conflict_checks").select("*").order("created_at", desc=True)
    if result: q = q.eq("result", result)
    return q.limit(limit).execute().data or []

@router.put("/decision")
async def record_decision(body: ConflictDecision, user=Depends(get_current_user)):
    update = {"decision": body.decision, "decision_notes": body.notes, "decision_at": datetime.utcnow().isoformat()}
    result = supabase.table("conflict_checks").update(update).eq("id", body.check_id).execute()
    if not result.data: raise HTTPException(404, "Vérification introuvable")
    return result.data[0]

@router.get("/stats")
async def conflict_stats(user=Depends(get_current_user)):
    all_c = supabase.table("conflict_checks").select("result,decision").execute()
    data = all_c.data or []
    return {"total": len(data), "rouge": sum(1 for c in data if c.get("result")=="rouge"), "orange": sum(1 for c in data if c.get("result")=="orange"), "vert": sum(1 for c in data if c.get("result")=="vert"), "refused": sum(1 for c in data if c.get("decision")=="refuse"), "accepted": sum(1 for c in data if c.get("decision")=="accepte")}
