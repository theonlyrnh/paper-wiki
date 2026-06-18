"""Two-step chain-of-thought ingestion pipeline — per-user data isolation."""

import os
import uuid
import json
import hashlib
import logging
import asyncio
from pathlib import Path
from datetime import datetime

from backend.config import CONFIG
from backend.database import get_db
from backend.services.llm_client import llm_analyze, llm_generate
from backend.services.embedding import is_configured as emb_configured
from backend.services.ingest_limits import ingest_semaphore, embedding_semaphore

logger = logging.getLogger(__name__)

WIKI_BASE = Path(__file__).parent.parent.parent / CONFIG["storage"]["wiki_dir"]

# Per-path file locks to prevent concurrent merge races on shared wiki files
_file_locks: dict[str, asyncio.Lock] = {}


def _get_file_lock(path: Path) -> asyncio.Lock:
    """Get or create an asyncio lock for a specific file path."""
    key = str(path)
    if key not in _file_locks:
        _file_locks[key] = asyncio.Lock()
    return _file_locks[key]

_BAD_FILENAMES = {
    "unknown", "untitled", "无标题", "未知",
    "paper", "entity", "concept", "source", "page",
}


def _sanitize_wiki_filename(raw: str, fallback_title: str, page_type: str) -> str:
    """Ensure wiki pages never get 'unknown' or other bad filenames."""
    import re as _re
    name = raw.strip()
    # Strip .md suffix for validation
    base = name[:-3] if name.endswith(".md") else name
    # Check if it's a bad filename
    if base.lower().replace("-", "").replace("_", "") in _BAD_FILENAMES or not base:
        # Generate slug from fallback_title
        slug = fallback_title.lower()
        # Keep alphanumeric, Chinese chars, hyphens
        slug = _re.sub(r'[^\w\u4e00-\u9fff-]', '-', slug)
        slug = _re.sub(r'-+', '-', slug).strip('-')
        if not slug:
            slug = f"{page_type}-{uuid.uuid4().hex[:8]}"
        # Prefix with type to avoid collisions
        base = f"{page_type}-{slug}" if slug == fallback_title.lower() else slug
        name = f"{base}.md"
    elif not name.endswith(".md"):
        name = f"{name}.md"
    return name


def _extract_title_from_content(content: str) -> str:
    """Extract title from YAML frontmatter or first H1 heading."""
    import re as _re
    # Try frontmatter
    fm_match = _re.match(r'^---\n(.*?)\n---', content, _re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split('\n'):
            if line.strip().startswith('title:'):
                title = line.split(':', 1)[1].strip().strip('"').strip("'")
                if title:
                    return title
    # Try first H1
    for line in content.split('\n')[:10]:
        if line.startswith('# '):
            title = line[2:].strip()
            if title and title.lower() not in ('unknown', 'untitled', '无标题'):
                return title
    return ""


def _get_wiki_dir(user_id: int) -> Path:
    """Get per-user wiki directory, creating if needed."""
    d = WIKI_BASE / str(user_id)
    for sub in ["sources", "entities", "concepts", "queries"]:
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def _read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug[:80]


async def run_ingestion(paper_id: str, paper_title: str, markdown_content: str, user_id: int = 1):
    async with ingest_semaphore:
        await _run_ingestion_unlocked(paper_id, paper_title, markdown_content, user_id=user_id)


async def _run_ingestion_unlocked(paper_id: str, paper_title: str, markdown_content: str, user_id: int = 1):
    """Run the full two-step ingestion pipeline for a paper."""
    db = await get_db()
    task_id = str(uuid.uuid4())
    wiki_dir = _get_wiki_dir(user_id)

    try:
        # Queue entry with user_id
        await db.execute(
            "INSERT INTO ingest_queue (id, user_id, paper_id, status, step) VALUES (?, ?, ?, 'queued', NULL)",
            (task_id, user_id, paper_id),
        )
        await db.execute(
            "UPDATE papers SET status = 'ingesting', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (paper_id, user_id),
        )
        await db.commit()

        # Step 1: Analyze
        await _update_task(db, task_id, "analyzing", "LLM 分析中...")
        logger.info(f"Ingest {task_id}: Step 1 — Analyzing '{paper_title}'")

        wiki_context = _build_wiki_context(wiki_dir)
        analysis = await llm_analyze(markdown_content, wiki_context)

        logger.info(
            f"Ingest {task_id}: Analysis complete — "
            f"{len(analysis.get('key_entities', []))} entities, "
            f"{len(analysis.get('key_concepts', []))} concepts"
        )

        # Step 2: Generate
        await _update_task(db, task_id, "generating", "LLM 生成 Wiki 页面...")
        logger.info(f"Ingest {task_id}: Step 2 — Generating wiki pages")

        wiki_structure = _build_wiki_structure(wiki_dir)
        generation = await llm_generate(analysis, wiki_structure)

        # Write wiki pages
        await _update_task(db, task_id, "writing", "写入 Wiki 文件...")

        # Source page
        source = generation.get("source_page", {})
        if source.get("filename") and source.get("content"):
            source_filename = _sanitize_wiki_filename(
                source["filename"], analysis.get("title", paper_title), "source"
            )
            source_path = wiki_dir / "sources" / source_filename
            _write_file(source_path, source["content"])
            await _upsert_wiki_page(db, source_filename, "source", str(source_path),
                                     analysis.get("title", paper_title), paper_id,
                                     analysis.get("tags", []), user_id)
            await db.execute(
                "UPDATE papers SET wiki_source_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (str(source_path), paper_id, user_id),
            )
            logger.info(f"  Written source: {source_filename}")

        # Entity pages
        for page in generation.get("entity_pages", []):
            if page.get("filename") and page.get("content"):
                entity_filename = _sanitize_wiki_filename(
                    page["filename"], page.get("filename", "").replace(".md", ""), "entity"
                )
                entity_path = wiki_dir / "entities" / entity_filename
                async with _get_file_lock(entity_path):
                    existing = entity_path.exists()
                    if page.get("action") == "update" and existing:
                        old = _read_file(entity_path)
                        new_content = _merge_wiki_page(old, page["content"], paper_id)
                    else:
                        new_content = page["content"]
                    _write_file(entity_path, new_content)
                # Extract title from content frontmatter, fallback to filename-derived
                entity_title = _extract_title_from_content(new_content)
                if not entity_title:
                    entity_title = entity_filename.replace(".md", "").replace("-", " ").title()
                await _upsert_wiki_page(db, entity_filename, "entity", str(entity_path),
                                         entity_title, paper_id, analysis.get("tags", []), user_id)
                logger.info(f"  Written entity: {entity_filename} ({page.get('action', 'create')})")

        # Concept pages
        for page in generation.get("concept_pages", []):
            if page.get("filename") and page.get("content"):
                concept_filename = _sanitize_wiki_filename(
                    page["filename"], page.get("filename", "").replace(".md", ""), "concept"
                )
                concept_path = wiki_dir / "concepts" / concept_filename
                async with _get_file_lock(concept_path):
                    existing = concept_path.exists()
                    if page.get("action") == "update" and existing:
                        old = _read_file(concept_path)
                        new_content = _merge_wiki_page(old, page["content"], paper_id)
                    else:
                        new_content = page["content"]
                    _write_file(concept_path, new_content)
                concept_title = _extract_title_from_content(new_content)
                if not concept_title:
                    concept_title = concept_filename.replace(".md", "").replace("-", " ").title()
                await _upsert_wiki_page(db, concept_filename, "concept", str(concept_path),
                                         concept_title, paper_id, analysis.get("tags", []), user_id)
                logger.info(f"  Written concept: {concept_filename} ({page.get('action', 'create')})")

        # Update index/log/overview (per-user) — locked to prevent append races
        index_path = wiki_dir / "index.md"
        log_path = wiki_dir / "log.md"
        overview_path = wiki_dir / "overview.md"

        index_addition = _extract_index_addition(generation)
        if index_addition:
            async with _get_file_lock(index_path):
                old_index = _read_file(index_path)
                _write_file(index_path, old_index.rstrip() + "\n\n" + index_addition + "\n")

        log_entry = generation.get("log_entry", "")
        if log_entry:
            async with _get_file_lock(log_path):
                old_log = _read_file(log_path)
                today = datetime.now().strftime("%Y-%m-%d")
                _write_file(log_path, old_log.rstrip() + f"\n- {today}: {log_entry}\n")

        overview_update = generation.get("overview_update", "")
        if overview_update:
            async with _get_file_lock(overview_path):
                old_overview = _read_file(overview_path)
                _write_file(overview_path, old_overview.rstrip() + "\n\n" + overview_update + "\n")

        # Vector indexing
        await _update_task(db, task_id, "indexing", "生成向量索引...")
        await _index_wiki_pages(wiki_dir, user_id)

        # Mark complete
        await db.execute(
            "UPDATE papers SET status = 'done', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (paper_id, user_id),
        )
        await _update_task(db, task_id, "done", None)
        await db.commit()
        logger.info(f"Ingest {task_id}: Complete ✓")

    except Exception as e:
        logger.exception(f"Ingest {task_id} failed: {e}")
        error_type = getattr(e, "error_type", type(e).__name__)
        await db.execute(
            "UPDATE papers SET status = 'failed', error_msg = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (str(e)[:500], paper_id, user_id),
        )
        await _update_task(db, task_id, "failed", str(e)[:500], error_type=error_type)
        await db.commit()
    finally:
        await db.close()


def _extract_index_addition(generation: dict) -> str:
    """Read both historic singular and prompt plural index addition fields."""
    return generation.get("index_addition") or generation.get("index_additions") or ""


async def _update_task(db, task_id: str, status: str, error: str = None, error_type: str = None):
    await db.execute(
        """UPDATE ingest_queue
           SET status = ?, step = ?, error_msg = ?, error_type = COALESCE(?, error_type),
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (status, status, error, error_type, task_id),
    )
    await db.commit()


async def _index_wiki_pages(wiki_dir: Path = None, user_id: int = None):
    """Index wiki pages into the vector store (per-user)."""
    if not emb_configured():
        logger.info("Embedding not configured, skipping vector indexing")
        return

    from backend.services.vector_store import get_vector_store
    vs = get_vector_store()
    indexed = 0

    dirs_to_scan = [wiki_dir] if wiki_dir else [WIKI_BASE]
    if not wiki_dir and WIKI_BASE.exists():
        dirs_to_scan = [d for d in WIKI_BASE.iterdir() if d.is_dir()]

    for base_dir in dirs_to_scan:
        if not base_dir or not base_dir.exists():
            continue
        uid = user_id
        if uid is None and base_dir != WIKI_BASE:
            try:
                uid = int(base_dir.name)
            except ValueError:
                continue

        for subdir in ["sources", "entities", "concepts", ""]:
            search_dir = base_dir / subdir if subdir else base_dir
            if not search_dir.exists():
                continue
            for md_file in search_dir.glob("*.md"):
                if not subdir and md_file.name in ("index.md", "log.md", "overview.md"):
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                    title = md_file.stem.replace("-", " ").title()
                    for line in content.split("\n")[:10]:
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break
                    page_type = subdir or "root"
                    # Normalize to singular for API compatibility
                    _PTYPE = {"sources": "source", "entities": "entity", "concepts": "concept"}
                    page_type = _PTYPE.get(page_type, page_type)
                    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                    vec_name = f"u{uid}_{md_file.stem}" if uid else md_file.stem
                    async with embedding_semaphore:
                        await vs.upsert_async(
                            name=vec_name, page_type=page_type,
                            title=title, content=content, content_hash=content_hash,
                        )
                    indexed += 1
                except Exception as e:
                    logger.warning(f"Failed to index {md_file.name}: {e}")

    logger.info(f"Vector indexed {indexed} wiki pages")


def _build_wiki_context(wiki_dir: Path = None) -> str:
    """Build context string from current wiki state."""
    if wiki_dir is None:
        wiki_dir = WIKI_BASE
    parts = []

    index = _read_file(wiki_dir / "index.md")
    if index:
        parts.append(f"### index.md\n{index[:3000]}")

    overview = _read_file(wiki_dir / "overview.md")
    if overview:
        parts.append(f"### overview.md\n{overview[:2000]}")

    for subdir in ["entities", "concepts"]:
        d = wiki_dir / subdir
        if d.exists():
            files = sorted(d.glob("*.md"))
            if files:
                titles = []
                for f in files[:30]:
                    content = _read_file(f)
                    title = f.stem.replace("-", " ").title()
                    for line in content.split("\n")[:5]:
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break
                    titles.append(f"- [[{title}]]")
                parts.append(f"### 已有 {subdir} 页面\n" + "\n".join(titles))

    return "\n\n".join(parts) if parts else "_知识库为空，这是第一篇论文。_"


def _build_wiki_structure(wiki_dir: Path = None) -> str:
    """Build a description of the current wiki structure."""
    if wiki_dir is None:
        wiki_dir = WIKI_BASE
    parts = []
    for subdir in ["sources", "entities", "concepts"]:
        d = wiki_dir / subdir
        if d.exists():
            files = sorted(d.glob("*.md"))
            if files:
                parts.append(f"{subdir}/: {', '.join(f.stem for f in files[:20])}")
            else:
                parts.append(f"{subdir}/: (空)")
        else:
            parts.append(f"{subdir}/: (不存在)")
    return "\n".join(parts)


async def _upsert_wiki_page(db, name: str, page_type: str, path: str,
                              title: str, paper_id: str, tags: list, user_id: int):
    """Insert or update a wiki_pages record with user_id."""
    page_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wiki/{user_id}/{page_type}/{name}"))
    tags_json = json.dumps(tags) if tags else None

    cursor = await db.execute(
        "SELECT id FROM wiki_pages WHERE user_id = ? AND type = ? AND name = ?",
        (user_id, page_type, name),
    )
    existing = await cursor.fetchone()

    if existing:
        cursor2 = await db.execute(
            "SELECT sources FROM wiki_pages WHERE user_id = ? AND type = ? AND name = ?",
            (user_id, page_type, name),
        )
        row = await cursor2.fetchone()
        old_sources = json.loads(row["sources"]) if row and row["sources"] else []
        if paper_id not in old_sources:
            old_sources.append(paper_id)
        await db.execute(
            """UPDATE wiki_pages SET path=?, title=?, sources=?, tags=?,
               updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND type=? AND name=?""",
            (path, title, json.dumps(old_sources), tags_json, user_id, page_type, name),
        )
    else:
        await db.execute(
            """INSERT INTO wiki_pages (id, user_id, name, type, path, title, sources, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (page_id, user_id, name, page_type, path, title, json.dumps([paper_id]), tags_json),
        )
    await db.commit()


def _merge_wiki_page(old_content: str, new_content: str, paper_id: str) -> str:
    old_lines = old_content.strip().split("\n")

    fm_end = 0
    if old_lines and old_lines[0] == "---":
        for i, line in enumerate(old_lines[1:], 1):
            if line == "---":
                fm_end = i + 1
                break

    if fm_end > 0:
        new_fm_lines = []
        for line in old_lines[1:fm_end - 1]:
            if line.startswith("sources:"):
                try:
                    src = json.loads(line.split(":", 1)[1].strip())
                    if paper_id not in src:
                        src.append(paper_id)
                    line = f"sources: {json.dumps(src)}"
                except (json.JSONDecodeError, IndexError):
                    pass
            new_fm_lines.append(line)
        header = "---\n" + "\n".join(new_fm_lines) + "\n---"
        body = "\n".join(old_lines[fm_end:])
        old_content = header + "\n" + body

    new_lines = new_content.strip().split("\n")
    new_fm_end = 0
    if new_lines and new_lines[0] == "---":
        for i, line in enumerate(new_lines[1:], 1):
            if line == "---":
                new_fm_end = i + 1
                break

    new_body = "\n".join(new_lines[new_fm_end:]).strip() if new_fm_end > 0 else new_content.strip()
    return old_content.rstrip() + "\n\n" + new_body + "\n"
