"""Per-user raw PDF storage quota helpers."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from backend.config import CONFIG, get_storage_path

RAW_PDF_QUOTA_MB = int(CONFIG.get("storage", {}).get("raw_pdf_quota_mb", 1000))
RAW_PDF_RETENTION_DAYS = int(CONFIG.get("storage", {}).get("raw_pdf_retention_days", 7))
RAW_DIR = get_storage_path("raw_dir")
MB = 1024 * 1024


def bytes_to_mb(value: int) -> float:
    """Convert bytes to MB rounded for UI display."""
    return round(value / MB, 3)


def raw_pdf_user_dir(user_id: int) -> Path:
    """Return the user's raw PDF directory without requiring it to already exist."""
    return RAW_DIR / str(user_id)


def raw_pdf_usage_bytes(user_dir: Path) -> int:
    """Count only PDF files under a user's raw upload directory."""
    if not user_dir.exists():
        return 0
    total = 0
    for path in user_dir.iterdir():
        if path.is_file() and path.suffix.lower() == ".pdf":
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def quota_status_from_dir(user_dir: Path, quota_mb: int = RAW_PDF_QUOTA_MB) -> dict:
    """Build raw PDF quota status from a user directory."""
    used_bytes = raw_pdf_usage_bytes(user_dir)
    quota_bytes = quota_mb * MB
    remaining_bytes = max(0, quota_bytes - used_bytes)
    usage_percent = 0 if quota_bytes <= 0 else min(100, round(used_bytes / quota_bytes * 100, 1))
    return {
        "used_bytes": used_bytes,
        "quota_bytes": quota_bytes,
        "remaining_bytes": remaining_bytes,
        "used_mb": bytes_to_mb(used_bytes),
        "quota_mb": quota_mb,
        "remaining_mb": bytes_to_mb(remaining_bytes),
        "usage_percent": usage_percent,
        "can_upload": used_bytes < quota_bytes,
    }


def quota_status_for_user(user_id: int, quota_mb: int = RAW_PDF_QUOTA_MB) -> dict:
    """Build raw PDF quota status for a user id."""
    return quota_status_from_dir(raw_pdf_user_dir(user_id), quota_mb=quota_mb)


def ensure_upload_fits_quota(status: dict, upload_size: int) -> None:
    """Raise ValueError when uploading a file would exceed the user's quota."""
    used = int(status.get("used_bytes", 0))
    quota = int(status.get("quota_bytes", RAW_PDF_QUOTA_MB * MB))
    if used >= quota:
        raise ValueError("上传文件空间已满，请先删除已解析论文的原始 PDF 释放空间后再上传。")
    if used + upload_size > quota:
        used_mb = bytes_to_mb(used)
        quota_mb = bytes_to_mb(quota)
        upload_mb = bytes_to_mb(upload_size)
        raise ValueError(
            f"上传失败：您已使用 {used_mb}MB / {quota_mb}MB，该文件大小为 {upload_mb}MB，上传后将超过您的空间配额。"
        )


def _parse_db_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            try:
                dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_cleanup_candidate(row, pdf_path: Path, now: datetime | None = None, retention_days: int = RAW_PDF_RETENTION_DAYS) -> bool:
    """Return True when a paper's original PDF can be safely auto-cleaned."""
    def _get(key):
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            return row.get(key) if hasattr(row, "get") else None

    status = _get("status")
    markdown_path = _get("markdown_path")
    updated_at = _get("updated_at")
    created_at = _get("created_at")

    if status != "done":
        return False
    if not pdf_path.exists():
        return False
    if not markdown_path or not Path(markdown_path).exists():
        return False

    reference_time = _parse_db_datetime(updated_at) or _parse_db_datetime(created_at)
    if reference_time is None:
        return False
    now = now or datetime.utcnow()
    return (now - reference_time).total_seconds() >= retention_days * 24 * 60 * 60


async def cleanup_expired_raw_pdfs(db, user_id: int, retention_days: int = RAW_PDF_RETENTION_DAYS) -> dict:
    """Delete expired raw PDFs for one user using conservative safety checks."""
    cursor = await db.execute(
        "SELECT id, filename, status, markdown_path, created_at, updated_at FROM papers WHERE user_id = ?",
        (user_id,),
    )
    rows = await cursor.fetchall()
    deleted = []
    freed_bytes = 0
    user_dir = raw_pdf_user_dir(user_id)
    now = datetime.utcnow()

    for row in rows:
        pdf_path = user_dir / row["filename"]
        if not is_cleanup_candidate(row, pdf_path, now=now, retention_days=retention_days):
            continue
        try:
            size = pdf_path.stat().st_size
            pdf_path.unlink()
            deleted.append(row["id"])
            freed_bytes += size
        except OSError:
            continue

    return {
        "deleted_count": len(deleted),
        "freed_bytes": freed_bytes,
        "freed_mb": bytes_to_mb(freed_bytes),
        "paper_ids": deleted,
    }
