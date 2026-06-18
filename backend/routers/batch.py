"""Batch import API — per-user isolation."""

import uuid
import hashlib
import logging
import asyncio
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends

from backend.config import get_storage_path
from backend.database import get_db
from backend.auth import get_current_user
from backend.services.storage_quota import quota_status_for_user, ensure_upload_fits_quota

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/batch", tags=["batch"])

RAW_DIR = get_storage_path("raw_dir")
def _compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@router.post("/upload")
async def batch_upload(
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    pdf_files = [f for f in files if f.filename.lower().endswith(".pdf")]
    if not pdf_files:
        raise HTTPException(400, "No PDF files in upload")

    uid = current_user["id"]
    user_dir = RAW_DIR / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)
    quota_status = quota_status_for_user(uid)
    planned_used_bytes = quota_status["used_bytes"]

    results = []
    for file in pdf_files:
        paper_id = str(uuid.uuid4())
        filename = file.filename

        save_path = user_dir / filename
        if save_path.exists():
            stem = save_path.stem
            suffix = save_path.suffix
            counter = 1
            while save_path.exists():
                save_path = user_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            filename = save_path.name

        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()
        title = Path(filename).stem.replace("-", " ").replace("_", " ").title()

        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id FROM papers WHERE user_id = ? AND file_hash = ?", (uid, file_hash)
            )
            existing = await cursor.fetchone()
            if existing:
                results.append({
                    "filename": filename, "status": "skipped",
                    "message": f"Duplicate (existing paper {existing['id'][:8]})",
                    "id": existing["id"],
                })
                continue

            try:
                ensure_upload_fits_quota(
                    {**quota_status, "used_bytes": planned_used_bytes},
                    len(content),
                )
            except ValueError as exc:
                results.append({
                    "filename": filename,
                    "status": "rejected",
                    "message": str(exc),
                    "id": None,
                })
                continue

            with open(save_path, "wb") as f:
                f.write(content)
            planned_used_bytes += len(content)

            await db.execute(
                "INSERT INTO papers (id, user_id, title, filename, file_hash, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                (paper_id, uid, title, filename, file_hash),
            )
            await db.commit()
        finally:
            await db.close()

        asyncio.create_task(_process_paper_batch(paper_id, str(save_path), uid))
        results.append({
            "filename": filename, "status": "queued",
            "message": "Paper queued for parsing", "id": paper_id,
        })

    accepted = sum(1 for r in results if r["status"] == "queued")
    rejected = sum(1 for r in results if r["status"] == "rejected")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    return {
        "total": len(files),
        "accepted": accepted,
        "rejected": rejected,
        "skipped": skipped,
        "results": results,
    }


async def _process_paper_batch(paper_id: str, pdf_path: str, user_id: int):
    from backend.routers.papers import _process_paper
    await _process_paper(paper_id, pdf_path, user_id)


@router.get("/progress")
async def batch_progress(current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT status, COUNT(*) as count FROM papers
            WHERE user_id = ? GROUP BY status
        """, (current_user["id"],))
        rows = await cursor.fetchall()
        status_counts = {r["status"]: r["count"] for r in rows}
        total = sum(status_counts.values())
        return {
            "total": total,
            "done": status_counts.get("done", 0),
            "failed": status_counts.get("failed", 0),
            "in_progress": total - status_counts.get("done", 0) - status_counts.get("failed", 0),
            "by_status": status_counts,
        }
    finally:
        await db.close()
