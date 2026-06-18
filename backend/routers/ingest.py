"""Ingest management API router — per-user isolation."""

from fastapi import APIRouter, HTTPException, Depends
from backend.database import get_db
from backend.models import IngestStatusItem
from backend.auth import get_current_user

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/status", response_model=list[IngestStatusItem])
async def get_ingest_status(current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT iq.*, p.title as paper_title
               FROM ingest_queue iq
               LEFT JOIN papers p ON iq.paper_id = p.id
               WHERE iq.user_id = ?
               ORDER BY iq.created_at DESC LIMIT 50""",
            (current_user["id"],),
        )
        rows = await cursor.fetchall()
        return [
            IngestStatusItem(
                id=r["id"], paper_id=r["paper_id"], paper_title=r["paper_title"],
                status=r["status"], step=r["step"], retry_count=r["retry_count"],
                error_msg=r["error_msg"],
                created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]
    finally:
        await db.close()


@router.post("/cancel/{task_id}")
async def cancel_ingest(task_id: str, current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ingest_queue WHERE id = ? AND user_id = ?",
            (task_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Ingest task not found")
        if row["status"] in ("done", "failed"):
            raise HTTPException(400, f"Cannot cancel task in status '{row['status']}'")

        await db.execute(
            "UPDATE ingest_queue SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (task_id, current_user["id"]),
        )
        await db.commit()
        return {"message": "Task cancelled", "id": task_id}
    finally:
        await db.close()


@router.post("/retry/{task_id}")
async def retry_ingest(task_id: str, current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ingest_queue WHERE id = ? AND user_id = ?",
            (task_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Ingest task not found")
        if row["status"] != "failed":
            raise HTTPException(400, "Can only retry failed tasks")

        await db.execute(
            "UPDATE ingest_queue SET status = 'queued', error_msg = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (task_id, current_user["id"]),
        )
        await db.commit()
        return {"message": "Task queued for retry", "id": task_id}
    finally:
        await db.close()
