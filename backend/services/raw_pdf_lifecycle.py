"""Lifecycle helpers for user-uploaded raw PDF files."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone


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


def can_delete_raw_pdf(row, pdf_path: Path, now: datetime | None = None) -> tuple[bool, str | None]:
    """Check whether a raw PDF can be manually deleted safely."""
    def _get(key):
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            return row.get(key) if hasattr(row, "get") else None

    status = _get("status")
    markdown_path = _get("markdown_path")
    if status != "done":
        return False, "只有解析完成并生成 Markdown 的论文才能删除原始 PDF"
    if not pdf_path.exists():
        return False, "原始 PDF 文件不存在"
    if not markdown_path or not Path(markdown_path).exists():
        return False, "Markdown 结果不存在，暂不允许删除原始 PDF"
    return True, None


def delete_raw_pdf_file(pdf_path: Path) -> dict:
    """Delete a raw PDF file only; keep markdown and cached evidence untouched."""
    freed_bytes = 0
    if pdf_path.exists():
        try:
            freed_bytes = pdf_path.stat().st_size
            pdf_path.unlink()
        except OSError as exc:
            return {"deleted": False, "freed_bytes": 0, "error": str(exc)}
    return {"deleted": True, "freed_bytes": freed_bytes}
