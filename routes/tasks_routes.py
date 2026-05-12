"""LEXARYS - Tasks / Rappels routes"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from database import supabase
from auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: Optional[str] = "normal"
    prospect_id: Optional[str] = None
    client_id: Optional[str] = None
    dossier_id: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None


@router.get("")
async def list_tasks(
    user=Depends(get_current_user),
    status: Optional[str] = None,
    prospect_id: Optional[str] = None,
    client_id: Optional[str] = None,
    dossier_id: Optional[str] = None,
    overdue_only: bool = False,
):
    q = supabase.table("tasks").select("*").eq("user_id", user["id"])
    if status:
        q = q.eq("status", status)
    if prospect_id:
        q = q.eq("prospect_id", prospect_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if dossier_id:
        q = q.eq("dossier_id", dossier_id)
    q = q.order("due_date", desc=False).order("created_at", desc=True)
    res = q.execute()
    items = res.data or []
    if overdue_only:
        now_iso = datetime.utcnow().isoformat()
        items = [t for t in items if t.get("due_date") and t["due_date"] < now_iso and t.get("status") != "done"]
    return items


@router.get("/upcoming")
async def upcoming_tasks(user=Depends(get_current_user), days: int = 7):
    """Tasks due in the next N days + all overdue."""
    res = supabase.table("tasks").select("*").eq("user_id", user["id"]).neq("status", "done").order("due_date").execute()
    return res.data or []


@router.get("/stats")
async def task_stats(user=Depends(get_current_user)):
    res = supabase.table("tasks").select("status,due_date,priority").eq("user_id", user["id"]).execute()
    rows = res.data or []
    now = datetime.utcnow().isoformat()
    overdue = sum(1 for t in rows if t.get("due_date") and t["due_date"] < now and t.get("status") != "done")
    today = sum(1 for t in rows if t.get("due_date") and t["due_date"][:10] == now[:10] and t.get("status") != "done")
    pending = sum(1 for t in rows if t.get("status") in ("pending", "in_progress"))
    done = sum(1 for t in rows if t.get("status") == "done")
    return {"total": len(rows), "overdue": overdue, "today": today, "pending": pending, "done": done}


@router.post("")
async def create_task(body: TaskCreate, user=Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user["id"]
    if isinstance(data.get("due_date"), datetime):
        data["due_date"] = data["due_date"].isoformat()
    result = supabase.table("tasks").insert(data).execute()
    return result.data[0] if result.data else {}


@router.put("/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, user=Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    if "status" in data and data["status"] == "done":
        data["completed_at"] = datetime.utcnow().isoformat()
    if isinstance(data.get("due_date"), datetime):
        data["due_date"] = data["due_date"].isoformat()
    data["updated_at"] = datetime.utcnow().isoformat()
    res = supabase.table("tasks").update(data).eq("id", task_id).eq("user_id", user["id"]).execute()
    return res.data[0] if res.data else {}


@router.post("/{task_id}/complete")
async def complete_task(task_id: str, user=Depends(get_current_user)):
    now = datetime.utcnow().isoformat()
    res = supabase.table("tasks").update({"status": "done", "completed_at": now, "updated_at": now}).eq("id", task_id).eq("user_id", user["id"]).execute()
    return res.data[0] if res.data else {}


@router.delete("/{task_id}")
async def delete_task(task_id: str, user=Depends(get_current_user)):
    supabase.table("tasks").delete().eq("id", task_id).eq("user_id", user["id"]).execute()
    return {"ok": True}


# ============ NOTES ============
class NoteCreate(BaseModel):
    entity_type: str
    entity_id: str
    content: str


@router.get("/notes")
async def list_notes(entity_type: str, entity_id: str, user=Depends(get_current_user)):
    res = supabase.table("entity_notes").select("*").eq("user_id", user["id"]).eq("entity_type", entity_type).eq("entity_id", entity_id).order("created_at", desc=True).execute()
    return res.data or []


@router.post("/notes")
async def create_note(body: NoteCreate, user=Depends(get_current_user)):
    data = body.model_dump()
    data["user_id"] = user["id"]
    res = supabase.table("entity_notes").insert(data).execute()
    return res.data[0] if res.data else {}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, user=Depends(get_current_user)):
    supabase.table("entity_notes").delete().eq("id", note_id).eq("user_id", user["id"]).execute()
    return {"ok": True}


# ============ ACTIVITY TIMELINE ============
@router.get("/activity")
async def list_activity(entity_type: str, entity_id: str, user=Depends(get_current_user)):
    res = supabase.table("activity_log").select("*").eq("user_id", user["id"]).eq("entity_type", entity_type).eq("entity_id", entity_id).order("created_at", desc=True).limit(50).execute()
    return res.data or []
