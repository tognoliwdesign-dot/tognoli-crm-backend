"""LEXARYS -- Conflits d'Interets (Art. 4 RIN) -- table reelle: conflicts"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ConflictCheckRequest, ConflictDecision
from auth import get_current_user

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

TABLE = "conflicts"


def _load_cabinet_entities():
    entities = []
    try:
        clients = supabase.table("clients").select("id,raison_sociale,siren,siret,status").execute()
        for c in (clients.data or []):
            name = c.get("raison_sociale", "")
            if name:
                entities.append({
                    "id": c["id"],
                    "name": name,
                    "type": "client_actuel" if c.get("status") == "actif" else "client_ancien",
                    "siren": c.get("siren"),
                    "siret": c.get("siret"),
                })
    except Exception:
        pass

    try:
        dossiers = supabase.table("dossiers").select("id,reference,partie_adverse").execute()
        for d in (dossiers.data or []):
            pa = d.get("partie_adverse")
            if pa:
                entities.append({
                    "id": d["id"],
                    "name": pa,
                    "type": "partie_adverse",
                    "dossier_ref": d.get("reference"),
                })
    except Exception:
        pass

    return entities


def _check_conflicts(entity_name: str, siren: str, entities: list) -> dict:
    matches = []
    name_lower = entity_name.lower().strip()

    for e in entities:
        e_name = (e.get("name") or "").lower().strip()
        matched = False
        reason = ""

        if siren and e.get("siren") and siren == e["siren"]:
            matched = True
            reason = f"SIREN identique ({siren})"
        elif name_lower and e_name and name_lower == e_name:
            matched = True
            reason = "Nom identique"
        elif name_lower and e_name and (name_lower in e_name or e_name in name_lower) and len(name_lower) > 4:
            matched = True
            reason = f"Nom similaire: '{e['name']}'"

        if matched:
            matches.append({
                "entity_id": e["id"],
                "entity_name": e["name"],
                "entity_type": e["type"],
                "reason": reason,
                "dossier_ref": e.get("dossier_ref"),
            })

    if not matches:
        return {"result": "vert", "conflicts": [], "message": "Aucun conflit detecte"}

    has_current_client = any(m["entity_type"] == "client_actuel" for m in matches)
    result = "rouge" if has_current_client else "orange"
    msg = "Conflit direct avec client actuel" if has_current_client else "Conflit potentiel detecte"
    return {"result": result, "conflicts": matches, "message": msg}


@router.post("/check")
async def check_conflict(body: ConflictCheckRequest, user=Depends(get_current_user)):
    try:
        entities = _load_cabinet_entities()
        result = _check_conflicts(body.entity_name, body.siren, entities)

        check_id = None
        try:
            record = {
                "user_id": user["id"],
                "partie_adverse": body.entity_name,
                "type_conflit": "verification",
                "description": f"Verification: {body.entity_name} | SIREN: {body.siren or 'N/A'}",
                "statut": result["result"],
                "date_detection": datetime.utcnow().isoformat(),
            }
            saved = supabase.table(TABLE).insert(record).execute()
            if saved.data:
                check_id = saved.data[0]["id"]
        except Exception:
            pass

        return {**result, "check_id": check_id, "entity_name": body.entity_name}
    except Exception as e:
        raise HTTPException(500, f"Erreur verification conflit: {str(e)}")


@router.get("/history")
async def conflict_history(limit: int = 50, user=Depends(get_current_user)):
    try:
        result = supabase.table(TABLE).select("*").eq("user_id", user["id"]).order("created_at", desc=True).limit(limit).execute()
        rows = result.data or []
        return [{
            **r,
            "checked_entity_name": r.get("partie_adverse", ""),
            "result": r.get("statut", "vert"),
            "checked_at": r.get("date_detection") or r.get("created_at"),
        } for r in rows]
    except Exception:
        return []


@router.put("/decision")
async def record_decision(body: ConflictDecision, user=Depends(get_current_user)):
    try:
        statut_map = {
            "accepte": "accepte",
            "refuse": "refuse",
            "soumis_conseil_ordre": "soumis_ordre",
        }
        update = {
            "statut": statut_map.get(body.decision, body.decision),
            "description": body.notes or "",
            "date_resolution": datetime.utcnow().isoformat(),
        }
        result = supabase.table(TABLE).update(update).eq("id", body.check_id).execute()
        if not result.data:
            raise HTTPException(404, "Verification introuvable")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/stats")
async def conflict_stats(user=Depends(get_current_user)):
    try:
        all_checks = supabase.table(TABLE).select("statut,date_detection").eq("user_id", user["id"]).execute()
        data = all_checks.data or []
        total = len(data)
        return {
            "total": total,
            "total_checks": total,
            "rouge": sum(1 for c in data if c.get("statut") == "rouge"),
            "orange": sum(1 for c in data if c.get("statut") == "orange"),
            "vert": sum(1 for c in data if c.get("statut") == "vert"),
            "refused": sum(1 for c in data if c.get("statut") == "refuse"),
            "accepted": sum(1 for c in data if c.get("statut") == "accepte"),
            "pending_decision": sum(1 for c in data if c.get("statut") in ("rouge", "orange")),
        }
    except Exception:
        return {
            "total": 0, "total_checks": 0,
            "rouge": 0, "orange": 0, "vert": 0,
            "refused": 0, "accepted": 0, "pending_decision": 0
        }
