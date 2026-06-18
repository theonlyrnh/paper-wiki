"""Wiki page API router — per-user, with source paper highlights."""

import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from backend.config import CONFIG
from backend.auth import get_current_user
from backend.database import get_db
from backend.services.pdf_highlight_service import find_relevant_paragraphs, strip_markdown_for_highlight
import json

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

WIKI_BASE = Path(__file__).parent.parent.parent / CONFIG["storage"]["wiki_dir"]
RAW_BASE = Path(__file__).parent.parent.parent / CONFIG["storage"]["raw_dir"]

VALID_TYPES = {"source": "sources", "entity": "entities", "concept": "concepts", "root": ""}


def _is_unknown_title(title: str | None) -> bool:
    if not title:
        return True
    return str(title).strip().lower() in {"unknown", "untitled", "无标题", "未知"}


@router.get("/page/{page_type}/{name}")
async def get_wiki_page(
    page_type: str, name: str,
    current_user: dict = Depends(get_current_user),
):
    subdir = VALID_TYPES.get(page_type)
    if subdir is None:
        raise HTTPException(400, f"Invalid page type: {page_type}")

    user_id = current_user["id"]
    wiki_dir = WIKI_BASE / str(user_id)
    path = wiki_dir / (subdir or "") / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, f"Page not found: {page_type}/{name}")

    content = path.read_text(encoding="utf-8")
    title = name.replace("-", " ").title()
    for line in content.split("\n")[:10]:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    tags = []
    lines = content.split("\n")
    if lines and lines[0] == "---":
        for line in lines[1:]:
            if line == "---":
                break
            if line.startswith("tags:"):
                raw = line.split(":", 1)[1].strip()
                tags = [t.strip().strip('"').strip("'") for t in raw.strip("[]").split(",")]

    # Fetch source paper highlights
    source_highlights = []
    db = await get_db()
    try:
        # Try both with and without .md extension
        names_to_try = [name, name + ".md", name.replace(".md", "")]
        placeholders = ",".join("?" for _ in names_to_try)
        cursor = await db.execute(
            f"SELECT sources FROM wiki_pages WHERE user_id = ? AND name IN ({placeholders})",
            (user_id, *names_to_try),
        )
        row = await cursor.fetchone()
        if row and row["sources"]:
            try:
                source_ids = json.loads(row["sources"])
            except (json.JSONDecodeError, TypeError):
                source_ids = []
            for pid in source_ids[:2]:
                c2 = await db.execute(
                    "SELECT id, title, markdown_path FROM papers WHERE user_id = ? AND id = ?",
                    (user_id, pid),
                )
                paper = await c2.fetchone()
                if paper and paper["markdown_path"]:
                    paper_path = Path(paper["markdown_path"])
                    if paper_path.exists():
                        paper_md = paper_path.read_text(encoding="utf-8")
                        # Find relevant paragraphs using wiki title + content
                        relevant = find_relevant_paragraphs(paper_md, title + " " + content[:2000], top_n=5)
                        # Get paragraph text snippets
                        highlights = []
                        for p in relevant:
                            snippet = strip_markdown_for_highlight(p["text"])
                            if len(snippet) > 500:
                                snippet = snippet[:500] + "..."
                            norm_score = max(1, min(99, round(p["score"] / p.get("max_terms", 1) * 100)))
                            highlights.append({
                                "text": snippet,
                                "start_line": p["start"],
                                "end_line": p["end"],
                                "score": norm_score,
                            })
                        source_highlights.append({
                            "paper_id": paper["id"],
                            "paper_title": paper["title"],
                            "highlights": highlights,
                        })
                        if _is_unknown_title(title) and paper["title"]:
                            title = paper["title"]
    finally:
        await db.close()

    return {
        "name": name,
        "type": page_type,
        "title": title,
        "tags": tags,
        "content": content,
        "source_highlights": source_highlights,
    }


@router.get("/pages")
async def list_wiki_pages(
    page_type: str = None,
    current_user: dict = Depends(get_current_user),
):
    pages = []
    wiki_dir = WIKI_BASE / str(current_user["id"])
    types_to_scan = {page_type: VALID_TYPES[page_type]} if page_type in VALID_TYPES else VALID_TYPES

    for ptype, subdir in types_to_scan.items():
        search_dir = wiki_dir / subdir if subdir else wiki_dir
        if not search_dir.exists():
            continue
        for md_file in search_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md", "overview.md") and subdir:
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            title = md_file.stem.replace("-", " ").title()
            for line in content.split("\n")[:10]:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            pages.append({"name": md_file.stem, "type": ptype, "title": title})

    return {"pages": pages, "count": len(pages)}
