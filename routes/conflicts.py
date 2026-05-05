"""LEXARYS — Routes Vérification Conflits d'Intérêts (Art. 4 RIN)"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ConflictCheckRequest, ConflictDecision
from auth import get_current_user
from conflict_engine import ConflictEngine, EntityToCheck, RegisteredEntity, conflict_result_to_dict

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


def _ensure_conflict_checks_table():
    """Crée la table conflict_checks si elle n'existe pas."""
    sql = """
    CREATE TABLE IF NOT EXISTS conflict_checks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        checked_by UUID,
        checked_entity_name TEXT NOT NULL,
        checked_entity_siren TEXT,
        checked_entity_siret TEXT,
        checked_entity_type TEXT DEFAULT 'prospect',
        result TEXT NOT NULL,
        conflicts_found JSONB DEFAULT '[]',
        decision TEXT,
        decision_notes TEXT,
        decision_at TIMESTAMPTZ,
        checked_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    try:
        supabase.rpc("exec_sql", {"query": sql}).execute()
    except Exception:
        pass


def _load_cabinet_entities(user_id: str) -> list:
    """Charge toutes les entités enregistrées du cabinet."""
    entities = []
    try:
        clients = supabase.table("clients").select("id,company_name,last_name,first_name,siren,siret,status").execute()
        for c in (clients.data or []):
            name = c.get("company_name") or f"{c.get('last_name','')} {c.get('first_name','')}".strip()
            if not name:
                continue
            entity_type = "client_actuel" if c.get("status") == "actif" else "client_ancien"
            entities.append(RegisteredEntity(
                id=c["id"],
                name=name,
                entity_type=entity_type,
                siren=c.get("siren"),
                siret=c.get("siret"),
            ))
    except Exception:
        pass

    try:
        dossiers = supabase.table("dossiers").select("id,reference,partie_adverse_name,partie_adverse_siret").not_.is_("partie_adverse_name", "null").execute()
        for d in (dossiers.data or []):
            pa_name = d.get("partie_adverse_name")
            if not pa_name:
                continue
            entities.append(RegisteredEntity(
                id=d["id"],
                name=pa_name,
                entity_type="partie_adverse",
                siret=d.get("partie_adverse_siret"),
                dossier_ref=d.get("reference"),
            ))
    except Exception:
        pass

    return entities


@router.post("/check")
async def check_conflict(body: ConflictCheckRequest, user=Depends(get_current_user)):
    """Vérifie les conflits d'intérêts. Résultat : vert / orange / rouge."""
    _ensure_conflict_checks_table()
    entities = _load_cabinet_entities(user["id"])
    engine = ConflictEngine(entities)

    entity = EntityToCheck(
        name=body.entity_name,
        siren=body.siren,
        siret=body.siret,
    )
    result = engine.check(entity)
    result_dict = conflict_result_to_dict(result)

    check_record = {
        "checked_by": user["id"],
        "checked_entity_name": body.entity_name,
        "checked_entity_siren": body.siren,
        "checked_entity_siret": body.siret,
        "checked_entity_type": body.entity_type,
        "result": result.result,
        "conflicts_found": result_dict["conflicts"],
        "checked_at": datetime.utcnow().isoformat(),
    }
    check_id = None
    try:
        saved = supabase.table("conflict_checks").insert(check_record).execute()
        check_id = saved.data[0]["id"] if saved.data else None
    except Exception:
        pass

    return {**result_dict, "check_id": check_id}


@router.get("/history")
async def conflict_history(limit: int = 50, user=Depends(get_current_user)):
    """Historique des vérifications de conflits."""
    try:
        result = supabase.table("conflict_checks").select("*").order("checked_at", desc=True).limit(limit).execute()
        return result.data or []
    except Exception:
        return []


@router.put("/decision")
async def record_decision(body: ConflictDecision, user=Depends(get_current_user)):
    """Enregistre la décision de l'avocat suite à une vérification."""
    update = {
        "decision": body.decision,
        "decision_notes": body.notes,
        "decision_at": datetime.utcnow().isoformat(),
    }
    try:
        result = supabase.table("conflict_checks").update(update).eq("id", body.check_id).execute()
        if not result.data:
            raise HTTPException(404, "Vérification introuvable")
        return result.data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Erreur mise à jour décision")


@router.get("/stats")
async def conflict_stats(user=Depends(get_current_user)):
    """Statistiques des vérifications de conflits."""
    try:
        all_checks = supabase.table("conflict_checks").select("result,decision,checked_at").execute()
        data = all_checks.data or []
    except Exception:
        data = []
    total = len(data)
    return {
        "total": total,
        "total_checks": total,
        "rouge": sum(1 for c in data if c.get("result") == "rouge"),
        "orange": sum(1 for c in data if c.get("result") == "orange"),
        "vert": sum(1 for c in data if c.get("result") == "vert"),
        "refused": sum(1 for c in data if c.get("decision") == "refuse"),
        "accepted": sum(1 for c in data if c.get("decision") == "accepte"),
        "pending_decision": sum(1 for c in data if not c.get("decision") and c.get("result") != "vert"),
    }
