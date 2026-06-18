"""Paper management API router — with user_id data isolation."""

import os
import uuid
import json
import hashlib
import logging
import asyncio
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends
from typing import Optional

from backend.config import get_storage_path
from backend.database import get_db
from backend.models import PaperUploadResponse, PaperRetryResponse, PaperListItem, PaperDetail
from backend.services.mineru_client import parse_pdf
from backend.services.storage_quota import quota_status_for_user, ensure_upload_fits_quota, bytes_to_mb
from backend.services.evidence_cache import build_highlight_cache_key, cache_slices, get_cached_slices
from backend.services.pdf_highlight_service import (
    find_relevant_paragraphs,
    generate_pdf_highlight_slices,
    strip_markdown_for_highlight,
)
from backend.services.raw_pdf_lifecycle import can_delete_raw_pdf, delete_raw_pdf_file
from backend.services.ingest_limits import parse_semaphore
from backend.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/papers", tags=["papers"])

RAW_DIR = get_storage_path("raw_dir")
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
IN_PROGRESS_STATUSES = {"pending", "parsing", "ingesting"}
RECENT_PROCESSING_WINDOW_SECONDS = 10 * 60

# Upload rate limiting (in-memory)
_upload_rate_limits: dict[str, list[float]] = {}


def _sanitize_filename(filename: str) -> str:
    """Clean filename to prevent path traversal and normalize."""
    # Remove path separators and nulls
    name = os.path.basename(filename)
    # Strip control chars and non-printable characters
    name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name)
    # Replace consecutive special chars with single underscore
    name = re.sub(r'[<>:"/\\|?*]+', '_', name)
    # Trim whitespace and limit length
    name = name.strip()[:255]
    return name or "unnamed.pdf"


def _compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_upload_rate(uid: int):
    key = f"upload:{uid}"
    now = time.time()
    window = 3600  # 1 hour
    max_reqs = 10
    _upload_rate_limits.setdefault(key, [])
    _upload_rate_limits[key] = [t for t in _upload_rate_limits[key] if now - t < window]
    if len(_upload_rate_limits[key]) >= max_reqs:
        raise HTTPException(429, "上传过于频繁，每小时最多 10 篇")
    _upload_rate_limits[key].append(now)


def _select_retry_mode(status: str, mode: str, has_markdown: bool) -> str:
    """Select parse/ingest retry mode from current paper status and assets."""
    mode = (mode or "auto").lower()
    if mode not in {"auto", "parse", "ingest"}:
        raise ValueError("Invalid retry mode")
    if mode != "auto":
        return mode
    if status == "done":
        raise ValueError("Paper is already done; use explicit mode")
    return "ingest" if has_markdown else "parse"


def _is_recently_updated(updated_at, window_seconds: int = RECENT_PROCESSING_WINDOW_SECONDS) -> bool:
    """Return True when a DB timestamp is inside the protected processing window."""
    if not updated_at:
        return False
    if isinstance(updated_at, datetime):
        updated = updated_at
    else:
        raw = str(updated_at).strip().replace("Z", "+00:00")
        try:
            updated = datetime.fromisoformat(raw)
        except ValueError:
            try:
                updated = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return False

    if updated.tzinfo is not None:
        updated = updated.astimezone(timezone.utc).replace(tzinfo=None)

    age = (datetime.utcnow() - updated).total_seconds()
    return age < window_seconds


def _llm_configured() -> bool:
    from backend.config import CONFIG
    llm_key = CONFIG.get("llm", {}).get("api_key", "")
    return bool(llm_key) and not llm_key.startswith("${")


@router.post("/upload", response_model=PaperUploadResponse)
async def upload_paper(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    _check_upload_rate(current_user["id"])
    # Validate filename
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    # Sanitize filename
    filename = _sanitize_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    paper_id = str(uuid.uuid4())
    user_id = current_user["id"]

    # Per-user storage
    user_dir = RAW_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    save_path = user_dir / filename

    # Read in chunks and validate — check file header (magic bytes)
    content = bytearray()
    # Read first 2KB for magic bytes check, then continue reading
    first_chunk = await file.read(2048)
    if not first_chunk:
        raise HTTPException(400, "Empty file")

    # PDF files must start with %PDF-
    if not first_chunk[:5] == b"%PDF-":
        raise HTTPException(400, "Invalid PDF file: file does not start with PDF header")

    content.extend(first_chunk)

    # Read remaining content with size limit
    total_read = len(first_chunk)
    while True:
        chunk = await file.read(65536)  # 64KB chunks
        if not chunk:
            break
        total_read += len(chunk)
        if total_read > MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"File too large: maximum {MAX_UPLOAD_SIZE // (1024*1024)} MB")
        content.extend(chunk)

    try:
        ensure_upload_fits_quota(quota_status_for_user(user_id), total_read)
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc

    with open(save_path, "wb") as f:
        f.write(content)

    file_hash = _compute_sha256(save_path)
    title = Path(filename).stem.replace("-", " ").replace("_", " ").title()

    db = await get_db()
    try:
        # Check duplicate within user's papers
        cursor = await db.execute(
            "SELECT id FROM papers WHERE user_id = ? AND file_hash = ?", (user_id, file_hash)
        )
        if await cursor.fetchone():
            save_path.unlink(missing_ok=True)
            raise HTTPException(409, "该文件已上传")

        await db.execute(
            """INSERT INTO papers (id, user_id, title, filename, file_hash, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (paper_id, user_id, title, filename, file_hash),
        )
        await db.commit()
    finally:
        await db.close()

    asyncio.create_task(_process_paper(paper_id, str(save_path), user_id))

    return PaperUploadResponse(
        id=paper_id, title=title, filename=filename,
        status="pending", message="Paper uploaded. Parsing started.",
    )


async def _process_paper(paper_id: str, pdf_path: str, user_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE papers SET status = 'parsing', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (paper_id, user_id),
        )
        await db.commit()

        async with parse_semaphore:
            result = await parse_pdf(pdf_path)

        if not result["success"]:
            await db.execute(
                "UPDATE papers SET status = 'failed', error_msg = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (result["error"], paper_id, user_id),
            )
            await db.commit()
            logger.error(f"Paper {paper_id} parsing failed: {result['error']}")
            return

        md_filename = Path(pdf_path).stem + ".md"
        md_path = Path(pdf_path).parent / md_filename
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(result["markdown"])

        title = None
        md_text = result["markdown"]

        for line in md_text.split("\n")[:30]:
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break

        if not title:
            try:
                from pypdf import PdfReader
                reader = PdfReader(pdf_path)
                meta = reader.metadata
                if meta and meta.title:
                    title = meta.title.strip()
            except Exception:
                pass

        if not title:
            skip_patterns = [
                "provided proper attribution", "reproduce the tables",
                "scholarly works", "copyright", "arxiv", "published at",
                "under review", "corresponding author", "<!-- ",
            ]
            candidates = []
            for line in md_text.split("\n")[:50]:
                line = line.strip()
                if not line or len(line) < 10 or len(line) > 150:
                    continue
                if line.startswith("<!--") or line.startswith("-->"):
                    continue
                lower = line.lower()
                if any(p in lower for p in skip_patterns):
                    continue
                if "@" in line or "∗" in line or "†" in line or "‡" in line:
                    continue
                if line.endswith("."):
                    continue
                words = line.split()
                if len(words) < 3:
                    continue
                caps = sum(1 for w in words if w[0].isupper() or not w[0].isalpha())
                if caps / len(words) > 0.5:
                    candidates.append(line)
                    if len(candidates) >= 3:
                        break
            if candidates:
                title = max(candidates, key=len)

        update_sql = """UPDATE papers SET
            status = 'done', markdown_path = ?, updated_at = CURRENT_TIMESTAMP"""
        params = [str(md_path)]
        if title:
            update_sql += ", title = ?"
            params.append(title)
        update_sql += " WHERE id = ? AND user_id = ?"
        params.extend([paper_id, user_id])
        await db.execute(update_sql, params)
        await db.commit()

        logger.info(f"Paper {paper_id} parsed: {len(result['markdown'])} chars")

        from backend.config import CONFIG
        llm_key = CONFIG.get("llm", {}).get("api_key", "")
        if llm_key and not llm_key.startswith("${"):
            from backend.services.ingest_pipeline import run_ingestion
            paper_title = title or Path(pdf_path).stem.replace("-", " ").title()
            asyncio.create_task(run_ingestion(paper_id, paper_title, result["markdown"], user_id=user_id))
        else:
            logger.info(f"Paper {paper_id}: No LLM API key, skipping ingestion")

    except Exception as e:
        logger.exception(f"Error processing paper {paper_id}")
        await db.execute(
            "UPDATE papers SET status = 'failed', error_msg = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (str(e), paper_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()


@router.post("/{paper_id}/ingest")
async def trigger_ingest(
    paper_id: str,
    current_user: dict = Depends(get_current_user),
):
    if not _llm_configured():
        raise HTTPException(400, "LLM API key not configured")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM papers WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Paper not found")
        if row["status"] not in ("done", "failed"):
            raise HTTPException(400, f"Paper status is '{row['status']}', must be 'done'")
        if not row["markdown_path"] or not Path(row["markdown_path"]).exists():
            raise HTTPException(400, "No markdown content available")

        md_content = Path(row["markdown_path"]).read_text(encoding="utf-8")
        from backend.services.ingest_pipeline import run_ingestion
        asyncio.create_task(run_ingestion(paper_id, row["title"], md_content, user_id=current_user["id"]))
        return {"message": "Ingestion triggered", "id": paper_id}
    finally:
        await db.close()


@router.post("/{paper_id}/retry", response_model=PaperRetryResponse)
async def retry_paper(
    paper_id: str,
    mode: str = Query("auto"),
    current_user: dict = Depends(get_current_user),
):
    """Retry a failed or stale paper by re-ingesting markdown or reparsing PDF."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM papers WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Paper not found")

        if row["status"] in IN_PROGRESS_STATUSES and _is_recently_updated(row["updated_at"]):
            raise HTTPException(409, "Paper is still being processed; please wait before retrying")

        md_path = Path(row["markdown_path"]) if row["markdown_path"] else None
        has_markdown = bool(md_path and md_path.exists())
        try:
            retry_mode = _select_retry_mode(row["status"], mode, has_markdown)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        if retry_mode == "ingest":
            if not has_markdown or not md_path:
                raise HTTPException(400, "No markdown content available")
            if not _llm_configured():
                raise HTTPException(400, "LLM API key not configured")

            try:
                md_content = md_path.read_text(encoding="utf-8")
            except Exception as exc:
                raise HTTPException(400, f"Cannot read markdown content: {exc}") from exc

            await db.execute(
                "UPDATE papers SET status = 'ingesting', error_msg = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (paper_id, current_user["id"]),
            )
            await db.commit()

            from backend.services.ingest_pipeline import run_ingestion
            asyncio.create_task(run_ingestion(paper_id, row["title"], md_content, user_id=current_user["id"]))
            return PaperRetryResponse(
                id=paper_id,
                mode=retry_mode,
                status="ingesting",
                message="Paper retry queued",
            )

        pdf_path = RAW_DIR / str(current_user["id"]) / row["filename"]
        if not pdf_path.exists():
            raise HTTPException(400, "Original PDF file not found")

        await db.execute(
            "UPDATE papers SET status = 'parsing', error_msg = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        await db.commit()

        asyncio.create_task(_process_paper(paper_id, str(pdf_path), current_user["id"]))
        return PaperRetryResponse(
            id=paper_id,
            mode=retry_mode,
            status="parsing",
            message="Paper retry queued",
        )
    finally:
        await db.close()


@router.get("", response_model=list[PaperListItem])
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    db = await get_db()
    try:
        offset = (page - 1) * page_size
        uid = current_user["id"]
        if status:
            cursor = await db.execute(
                "SELECT * FROM papers WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (uid, status, page_size, offset),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM papers WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (uid, page_size, offset),
            )
        rows = await cursor.fetchall()
        papers = []
        for row in rows:
            tags = json.loads(row["tags"]) if row["tags"] else None
            pdf_path = RAW_DIR / str(uid) / row["filename"]
            raw_pdf_size = 0
            if pdf_path.exists():
                try:
                    raw_pdf_size = pdf_path.stat().st_size
                except OSError:
                    raw_pdf_size = 0
            papers.append(PaperListItem(
                id=row["id"], title=row["title"], filename=row["filename"],
                authors=row["authors"], year=row["year"], tags=tags,
                status=row["status"],
                created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
                raw_pdf_available=pdf_path.exists(),
                raw_pdf_size_mb=bytes_to_mb(raw_pdf_size),
            ))
        return papers
    finally:
        await db.close()


@router.get("/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM papers WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Paper not found")

        md_content = None
        if row["markdown_path"] and Path(row["markdown_path"]).exists():
            with open(row["markdown_path"], "r", encoding="utf-8") as f:
                md_content = f.read()

        pdf_path = RAW_DIR / str(current_user["id"]) / row["filename"]
        raw_pdf_size = 0
        if pdf_path.exists():
            try:
                raw_pdf_size = pdf_path.stat().st_size
            except OSError:
                raw_pdf_size = 0

        tags = json.loads(row["tags"]) if row["tags"] else None
        return PaperDetail(
            id=row["id"], title=row["title"], filename=row["filename"],
            file_hash=row["file_hash"], authors=row["authors"], year=row["year"],
            tags=tags, status=row["status"], error_msg=row["error_msg"],
            markdown_path=row["markdown_path"], wiki_source_path=row["wiki_source_path"],
            created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
            markdown_content=md_content,
            raw_pdf_available=pdf_path.exists(),
            raw_pdf_size=raw_pdf_size,
            raw_pdf_size_mb=bytes_to_mb(raw_pdf_size),
        )
    finally:
        await db.close()


@router.delete("/{paper_id}")
async def delete_paper(
    paper_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM papers WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Paper not found")

        # Wiki base directory for this user
        from backend.config import CONFIG as _CFG
        wiki_base = Path(__file__).parent.parent.parent / _CFG["storage"]["wiki_dir"]
        wiki_dir = wiki_base / str(current_user["id"])
        _TYPE_DIR = {"source": "sources", "entity": "entities", "concept": "concepts"}

        # Delete wiki page files and DB records that only reference this paper
        cursor2 = await db.execute(
            "SELECT name, type, path, sources FROM wiki_pages WHERE user_id = ?",
            (current_user["id"],),
        )
        wiki_rows = await cursor2.fetchall()
        names_to_delete = []
        for wr in wiki_rows:
            try:
                srcs = json.loads(wr["sources"]) if wr["sources"] else []
            except (json.JSONDecodeError, TypeError):
                srcs = []
            if paper_id in srcs:
                srcs.remove(paper_id)
                if not srcs:
                    names_to_delete.append(wr["name"])
                    # Delete file: try stored path first, then wiki dir structure
                    deleted = False
                    if wr["path"] and Path(wr["path"]).exists():
                        Path(wr["path"]).unlink(missing_ok=True)
                        deleted = True
                    if not deleted:
                        subdir = _TYPE_DIR.get(wr["type"], "")
                        candidate = wiki_dir / (subdir or "") / f"{wr['name']}.md"
                        if candidate.exists():
                            candidate.unlink()
                else:
                    await db.execute(
                        "UPDATE wiki_pages SET sources = ? WHERE name = ? AND user_id = ?",
                        (json.dumps(srcs), wr["name"], current_user["id"]),
                    )

        # Delete orphan wiki pages from DB
        if names_to_delete:
            placeholders = ",".join("?" for _ in names_to_delete)
            await db.execute(
                f"DELETE FROM wiki_pages WHERE user_id = ? AND name IN ({placeholders})",
                (current_user["id"], *names_to_delete),
            )
            logger.info(f"Deleted {len(names_to_delete)} orphan wiki pages for paper {paper_id}")

        # Delete vector store entries for orphan pages
        try:
            from backend.services.vector_store import get_vector_store
            vs = get_vector_store()
            uid = current_user["id"]
            for name in names_to_delete:
                vs.delete(f"u{uid}_{name}")
        except Exception as e:
            logger.warning(f"Vector cleanup failed: {e}")

        # Invalidate graph cache so it rebuilds on next request
        try:
            from backend.routers.graph import _graph
            _graph.invalidate()
        except Exception:
            pass

        # Delete paper files
        for path_key in ("markdown_path",):
            if row[path_key]:
                p = Path(row[path_key])
                if p.exists():
                    p.unlink()

        pdf_path = RAW_DIR / str(current_user["id"]) / row["filename"]
        if pdf_path.exists():
            pdf_path.unlink()

        await db.execute("DELETE FROM papers WHERE id = ? AND user_id = ?",
                         (paper_id, current_user["id"]))
        await db.commit()
        return {"message": "Paper deleted", "id": paper_id,
                "wiki_pages_removed": len(names_to_delete)}
    finally:
        await db.close()


@router.post("/{paper_id}/pdf-highlights")
async def pdf_highlights(
    paper_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """Find and return PDF page image slices around the most relevant paragraphs.
    body: { snippets: [{text: str, start_line: int, end_line: int}, ...], query: str }
    Uses the search query to find matching paragraphs, then crops the PDF page image
    around those paragraphs. Returns base64-encoded PNG slices.
    """
    snippets = body.get("snippets", [])
    query = body.get("query", "")
    if not snippets and not query:
        raise HTTPException(400, "No snippets or query provided")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT title, filename, markdown_path FROM papers WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Paper not found")
        pdf_path = RAW_DIR / str(current_user["id"]) / row["filename"]
        cache_key = build_highlight_cache_key(query=query, snippets=snippets)
        cached = get_cached_slices(user_id=current_user["id"], paper_id=paper_id, cache_key=cache_key)
        if cached:
            return {
                "paper_title": cached.get("paper_title") or row["title"],
                "pdf_available": pdf_path.exists(),
                "cache_status": "hit",
                "cache_key": cache_key,
                "slices": cached["slices"],
            }
        if not pdf_path.exists():
            return {
                "paper_title": row["title"] or row["filename"].replace(".pdf", "")[:60],
                "pdf_available": False,
                "cache_status": "miss",
                "cache_key": cache_key,
                "reason": "PDF file not found",
                "fallback": "markdown",
                "markdown_available": bool(row["markdown_path"] and Path(row["markdown_path"]).exists()),
                "slices": [],
            }
    finally:
        await db.close()

    try:
        results = generate_pdf_highlight_slices(pdf_path=pdf_path, snippets=snippets, query=query)
    except Exception as e:
        raise HTTPException(500, f"Cannot open PDF: {e}")

    if results:
        cache_slices(
            user_id=current_user["id"],
            paper_id=paper_id,
            paper_title=row["title"] or row["filename"].replace(".pdf", "")[:60],
            filename=row["filename"],
            cache_key=cache_key,
            slices=results,
        )
    return {
        "paper_title": row["title"] or row["filename"].replace(".pdf", "")[:60],
        "pdf_available": True,
        "cache_status": "stored" if results else "miss",
        "cache_key": cache_key,
        "slices": results,
    }


@router.delete("/{paper_id}/raw-pdf")
async def delete_raw_pdf(
    paper_id: str,
    ensure_cache: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    """Delete only the uploaded raw PDF after parsed markdown exists.

    This releases quota space and keeps markdown/wiki/search/chat data intact.
    Evidence cache is preserved; if cache generation fails, deletion is still
    allowed because the product promise is that Markdown-based usage remains.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, title, filename, status, markdown_path FROM papers WHERE id = ? AND user_id = ?",
            (paper_id, current_user["id"]),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Paper not found")

        pdf_path = RAW_DIR / str(current_user["id"]) / row["filename"]
        allowed, reason = can_delete_raw_pdf(row, pdf_path)
        if not allowed:
            raise HTTPException(400, reason)

        cache_status = "skipped"
        cache_error = None
        if ensure_cache:
            try:
                md_text = Path(row["markdown_path"]).read_text(encoding="utf-8")
                cursor = await db.execute(
                    "SELECT name, title, path, sources FROM wiki_pages WHERE user_id = ?",
                    (current_user["id"],),
                )
                wiki_rows = await cursor.fetchall()
                stored_count = 0
                hit_count = 0
                empty_count = 0

                for wiki_row in wiki_rows:
                    try:
                        source_ids = json.loads(wiki_row["sources"]) if wiki_row["sources"] else []
                    except (json.JSONDecodeError, TypeError):
                        source_ids = []
                    if paper_id not in source_ids:
                        continue
                    wiki_path = Path(wiki_row["path"]) if wiki_row["path"] else None
                    if not wiki_path or not wiki_path.exists():
                        continue
                    wiki_content = wiki_path.read_text(encoding="utf-8")
                    wiki_title = wiki_row["title"] or wiki_row["name"].replace("-", " ").replace(".md", "").title()
                    relevant = find_relevant_paragraphs(md_text, wiki_title + " " + wiki_content[:2000], top_n=5)
                    snippets = []
                    for para in relevant:
                        snippet = strip_markdown_for_highlight(para["text"])
                        if len(snippet) > 500:
                            snippet = snippet[:500] + "..."
                        snippets.append({
                            "text": snippet,
                            "start_line": para["start"],
                            "end_line": para["end"],
                        })
                    if not snippets:
                        empty_count += 1
                        continue

                    cache_key = build_highlight_cache_key(query=wiki_title, snippets=snippets)
                    if get_cached_slices(user_id=current_user["id"], paper_id=paper_id, cache_key=cache_key):
                        hit_count += 1
                        continue
                    slices = generate_pdf_highlight_slices(pdf_path=pdf_path, snippets=snippets, query=wiki_title)
                    if slices:
                        cache_slices(
                            user_id=current_user["id"],
                            paper_id=paper_id,
                            paper_title=row["title"],
                            filename=row["filename"],
                            cache_key=cache_key,
                            slices=slices,
                        )
                        stored_count += 1
                    else:
                        empty_count += 1

                if stored_count:
                    cache_status = "stored"
                elif hit_count:
                    cache_status = "hit"
                elif empty_count:
                    cache_status = "empty"
                else:
                    cache_status = "no_sources"
            except Exception as exc:
                cache_status = "failed"
                cache_error = str(exc)
            if cache_status == "failed":
                raise HTTPException(500, f"来源切片缓存生成失败，原始 PDF 未删除：{cache_error}")

        result = delete_raw_pdf_file(pdf_path)
        if not result.get("deleted"):
            raise HTTPException(500, result.get("error") or "Failed to delete raw PDF")

        freed_bytes = int(result.get("freed_bytes", 0))
        return {
            "message": "原始 PDF 已删除，仅释放存储空间；Markdown、搜索、AI 问答和 Wiki 不受影响。",
            "deleted": True,
            "id": paper_id,
            "freed_bytes": freed_bytes,
            "freed_mb": bytes_to_mb(freed_bytes),
            "cache_status": cache_status,
            "cache_error": cache_error,
            "pdf_available": False,
            "quota": quota_status_for_user(current_user["id"]),
        }
    finally:
        await db.close()
