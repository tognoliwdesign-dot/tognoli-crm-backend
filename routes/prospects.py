"""LEXARYS - Routes Prospects"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from database import supabase
from models import ProspectCreate, ProspectUpdate, ProspectStatusUpdate
from auth import get_current_user

router = APIRouter(prefix="/prospects", tags=["prospects"])

PROSPECT_COLUMNS = {
    'user_id', 'raison_sociale', 'siren', 'siret', 'forme_juridique',
    'secteur_activite', 'code_naf', 'adresse', 'code_postal', 'ville',
    'effectif', 'chiffre_affaires', 'notes', 'source', 'tags',
    'statut', 'priority', 'score', 'score_breakdown',
    'capital_social', 'bodacc_procedure',
    'contact_name', 'contact_role', 'email', 'phone', 'website',
    'date_creation', 'assigned_to',
}

API_TO_DB = {
    'company_name':     'raison_sociale',
    'address':          'adresse',
    'postal_code':      'code_postal',
    'city':             'ville',
    'naf_code':         'code_naf',
    'naf_label':        'secteur_activite',
    'effectif_tranche': 'effectif',
    'priorite':         'priority',
}


def _to_db(data: dict) -> dict:
    translated = {}
    for k, v in data.items():
        db_key = API_TO_DB.get(k, k)
        translated[db_key] = v
    return {k: v for k, v in translated.items() if k in PROSPECT_COLUMNS and v is not None}


def _to_api(row: dict) -> dict:
    if not row:
        return row
    result = dict(row)
    if 'raison_sociale' in row:
        result['company_name'] = row['raison_sociale']
    if 'ville' in row:
        result['city'] = row['ville']
    if 'code_postal' in row:
        result['postal_code'] = row['code_postal']
    if 'code_naf' in row:
        result['naf_code'] = row['code_naf']
    if 'adresse' in row:
        result['address'] = row['adresse']
    if 'secteur_activite' in row:
        result['naf_label'] = row['secteur_activite']
    if 'statut' in row:
        result['status'] = row['statut']
    if 'priority' in row:
        result['priorite'] = row['priority']
    return result


@router.get("")
async def list_prospects(
    status: str = None,
    statut: str = None,
    search: str = None,
    priority: str = None,
    priorite: str = None,
    limit: int = 200,
    user=Depends(get_current_user)
):
    try:
        q = supabase.table("prospects").select("*").eq("user_id", user["id"])
        st = status or statut
        pr = priority or priorite
        if st:
            q = q.eq("status", st)
        if pr:
            q = q.eq("priority", pr)
        if search:
            q = q.ilike("raison_sociale", f"%{search}%")
        q = q.order("created_at", desc=True).limit(limit)
        result = q.execute()
        return [_to_api(r) for r in (result.data or [])]
    except Exception as e:
        raise HTTPException(500, f"Erreur liste prospects: {str(e)}")


@router.post("")
async def create_prospect(body: ProspectCreate, user=Depends(get_current_user)):
    try:
        raw = body.model_dump()
        raw["user_id"] = user["id"]
        if not raw.get("raison_sociale") and raw.get("company_name"):
            raw["raison_sociale"] = raw["company_name"]
        if not raw.get("raison_sociale"):
            raise HTTPException(400, "raison_sociale requis")
        if raw.get("date_creation"):
            raw["date_creation"] = str(raw["date_creation"])
        data = _to_db(raw)
        result = supabase.table("prospects").insert(data).execute()
        return _to_api(result.data[0]) if result.data else {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur creation prospect: {str(e)}")


@router.get("/stats")
async def prospect_stats(user=Depends(get_current_user)):
    try:
        all_p = supabase.table("prospects").select(
            "statut,priority,score_breakdown"
        ).eq("user_id", user["id"]).execute()
        data = all_p.data or []
        pipeline = {}
        for p in data:
            s = p.get("statut", "identifie")
            pipeline[s] = pipeline.get(s, 0) + 1
        scores = []
        for p in data:
            sb = p.get("score_breakdown")
            if sb:
                try:
                    import json
                    sc = json.loads(sb).get("score", 0) if isinstance(sb, str) else sb.get("score", 0)
                    if sc: scores.append(sc)
                except: pass
        urgent = sum(1 for p in data if p.get("priority") == "urgent")
        converti = pipeline.get("converti", 0)
        return {
            "total": len(data),
            "pipeline": pipeline,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "urgent": urgent,
            "high_priority": urgent,
            "converti": converti,
            "converted": converti,
            "deonto_alerts": sum(1 for p in data if p.get("has_formal_refusal")),
        }
    except Exception:
        return {"total": 0, "pipeline": {}, "avg_score": 0,
                "urgent": 0, "high_priority": 0, "converti": 0,
                "converted": 0, "deonto_alerts": 0}


@router.get("/{prospect_id}")
async def get_prospect(prospect_id: str, user=Depends(get_current_user)):
    try:
        result = supabase.table("prospects").select("*").eq("id", prospect_id).eq("user_id", user["id"]).execute()
        if not result.data:
            raise HTTPException(404, "Prospect introuvable")
        return _to_api(result.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/{prospect_id}")
async def update_prospect(prospect_id: str, body: ProspectUpdate, user=Depends(get_current_user)):
    try:
        raw = {k: v for k, v in body.model_dump().items() if v is not None}
        raw["updated_at"] = datetime.utcnow().isoformat()
        data = _to_db(raw)
        if not data:
            return {}
        result = supabase.table("prospects").update(data).eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/{prospect_id}/status")
async def update_status(prospect_id: str, body: ProspectStatusUpdate, user=Depends(get_current_user)):
    try:
        result = supabase.table("prospects").update({
            "statut": body.status,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return _to_api(result.data[0]) if result.data else {}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{prospect_id}/contact")
async def log_contact(prospect_id: str, contact_type: str, notes: str = None, user=Depends(get_current_user)):
    try:
        existing = supabase.table("prospects").select("statut").eq("id", prospect_id).execute()
        if not existing.data:
            raise HTTPException(404, "Prospect introuvable")
        if existing.data[0].get("has_formal_refusal"):
            raise HTTPException(403, "Prospect a refuse d'etre contacte.")
        try:
            supabase.table("prospect_contacts").insert({
                "prospect_id": prospect_id,
                "user_id": user["id"],
                "contact_type": contact_type,
                "notes": notes,
                "contact_date": datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            pass
        new_count = (existing.data[0].get("nb_contacts") or 0) + 1
        supabase.table("prospects").update({
            "nb_contacts": new_count,
            "last_contact_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", prospect_id).execute()
        return {"nb_contacts": new_count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{prospect_id}")
async def delete_prospect(prospect_id: str, user=Depends(get_current_user)):
    try:
        supabase.table("prospects").delete().eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(500, str(e))
