"""Maintenance helpers for ingestion state cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from backend.config import CONFIG
from backend.database import get_db

INGEST_CONFIG = CONFIG.get("ingest", {}) if isinstance(CONFIG.get("ingest", {}), dict) else {}
DEFAULT_STALE_AFTER_SECONDS = int(INGEST_CONFIG.get("stale_after_seconds", 1800) or 1800)

STALE_PAPER_STATUSES = ("pending", "parsing", "ingesting")
STALE_INGEST_STATUSES = ("queued", "processing", "analyzing", "generating", "writing", "indexing")
STALE_MESSAGE = "stale task: interrupted by server restart or exceeded processing window"


def _cutoff_timestamp(stale_after_seconds: int, now: Optional[str] = None) -> str:
    if now:
        base = datetime.strptime(now[:19], "%Y-%m-%d %H:%M:%S")
    else:
        base = datetime.utcnow()
    return (base - timedelta(seconds=stale_after_seconds)).strftime("%Y-%m-%d %H:%M:%S")


async def cleanup_stale_tasks(db=None, *, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS, now: Optional[str] = None) -> dict:
    """Mark stale in-progress paper and ingest states as failed.

    This is intentionally conservative: only statuses that should have an
    active in-process coroutine are touched, and only after a configurable
    inactivity window.
    """
    own_db = db is None
    if db is None:
        db = await get_db()

    cutoff = _cutoff_timestamp(stale_after_seconds, now=now)
    paper_placeholders = ",".join("?" for _ in STALE_PAPER_STATUSES)
    ingest_placeholders = ",".join("?" for _ in STALE_INGEST_STATUSES)

    try:
        cursor = await db.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM papers
            WHERE status IN ({paper_placeholders})
              AND updated_at < ?
            """,
            (*STALE_PAPER_STATUSES, cutoff),
        )
        papers_count = (await cursor.fetchone())["c"]

        await db.execute(
            f"""
            UPDATE papers
            SET status = 'failed',
                error_msg = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ({paper_placeholders})
              AND updated_at < ?
            """,
            (STALE_MESSAGE, *STALE_PAPER_STATUSES, cutoff),
        )

        cursor = await db.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM ingest_queue
            WHERE status IN ({ingest_placeholders})
              AND updated_at < ?
            """,
            (*STALE_INGEST_STATUSES, cutoff),
        )
        ingest_count = (await cursor.fetchone())["c"]

        await db.execute(
            f"""
            UPDATE ingest_queue
            SET status = 'failed',
                step = 'failed',
                error_type = 'stale_task',
                error_msg = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ({ingest_placeholders})
              AND updated_at < ?
            """,
            (STALE_MESSAGE, *STALE_INGEST_STATUSES, cutoff),
        )
        await db.commit()
        return {
            "papers_marked_failed": papers_count,
            "ingest_tasks_marked_failed": ingest_count,
            "cutoff": cutoff,
            "stale_after_seconds": stale_after_seconds,
        }
    finally:
        if own_db:
            await db.close()
