"""Search API router — per-user hybrid search with source paper enrichment."""

import json
import re
import time
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional
from backend.services.search_service import get_hybrid_search
from backend.auth import get_current_user
from backend.database import get_db

# Rate limiting (in-memory)
_search_rate_limits: dict[str, list[float]] = {}

router = APIRouter(prefix="/api/search", tags=["search"])

_hybrid_search = get_hybrid_search()


def _is_unknown_title(title: str | None) -> bool:
    if not title:
        return True
    return str(title).strip().lower() in {"unknown", "untitled", "无标题", "未知"}


def _fallback_title_from_name(name: str) -> str:
    return str(name or "").replace(".md", "").replace("-", " ").replace("_", " ").title()


def _check_search_rate(uid: int):
    key = f"search:{uid}"
    now = time.time()
    window = 60  # 1 minute
    max_reqs = 30
    _search_rate_limits.setdefault(key, [])
    _search_rate_limits[key] = [t for t in _search_rate_limits[key] if now - t < window]
    if len(_search_rate_limits[key]) >= max_reqs:
        raise HTTPException(429, "搜索过于频繁，请稍后再试")
    _search_rate_limits[key].append(now)


@router.get("")
async def search(
    q: str = Query(..., min_length=1),
    mode: str = Query("hybrid"),
    top_k: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    _check_search_rate(current_user["id"])
    use_bm25 = mode in ("hybrid", "bm25")
    use_vector = mode in ("hybrid", "vector")
    results = await _hybrid_search.search(
        q, top_k=top_k, use_bm25=use_bm25, use_vector=use_vector,
        user_id=current_user["id"],
    )

    # Enrich results with source paper info
    await _enrich_results(results, current_user["id"])

    return {"query": q, "mode": mode, "results": results, "count": len(results)}


async def _enrich_results(results: list[dict], user_id: int):
    """Add source paper info to each search result."""
    if not results:
        return
    db = await get_db()
    try:
        # Build lookup map: try both name and name.md
        all_names = set()
        for r in results:
            all_names.add(r["name"])
            all_names.add(r["name"] + ".md")
            all_names.add(r["name"].replace(".md", ""))
        placeholders = ",".join("?" for _ in all_names)
        cursor = await db.execute(
            f"SELECT name, title, sources FROM wiki_pages WHERE user_id = ? AND name IN ({placeholders})",
            (user_id, *all_names),
        )
        sources_by_name = {}
        titles_by_name = {}
        async for row in cursor:
            stem = row["name"].replace(".md", "")
            titles_by_name[row["name"]] = row["title"]
            titles_by_name[stem] = row["title"]
            try:
                sources = json.loads(row["sources"]) if row["sources"] else []
            except (json.JSONDecodeError, TypeError):
                sources = []
            if sources:
                papers = []
                for pid in sources[:3]:
                    c2 = await db.execute(
                        "SELECT id, title FROM papers WHERE user_id = ? AND id = ?",
                        (user_id, pid),
                    )
                    paper = await c2.fetchone()
                    if paper:
                        papers.append({"id": paper["id"], "title": paper["title"]})
                # Store under both variants
                sources_by_name[row["name"]] = papers
                sources_by_name[stem] = papers

        for r in results:
            papers = sources_by_name.get(r["name"], sources_by_name.get(r["name"] + ".md", []))
            r["papers"] = papers
            db_title = titles_by_name.get(r["name"], titles_by_name.get(r["name"] + ".md"))
            if _is_unknown_title(r.get("title")):
                if db_title and not _is_unknown_title(db_title):
                    r["title"] = db_title
                elif papers:
                    r["title"] = papers[0]["title"]
                else:
                    r["title"] = _fallback_title_from_name(r.get("name", ""))
            if r.get("snippet"):
                r["snippet"] = re.sub(r"^#\s*unknown\b\s*", "", r["snippet"], flags=re.IGNORECASE).strip()
    finally:
        await db.close()


@router.post("/reindex")
async def reindex(current_user: dict = Depends(get_current_user)):
    _hybrid_search.bm25.build_index(user_id=current_user["id"])
    return {"message": "BM25 index rebuilt"}


@router.post("/reindex-vectors")
async def reindex_vectors(current_user: dict = Depends(get_current_user)):
    from backend.services.ingest_pipeline import _index_wiki_pages, _get_wiki_dir
    wiki_dir = _get_wiki_dir(current_user["id"])
    await _index_wiki_pages(wiki_dir, current_user["id"])
    return {"message": "Vector reindex triggered"}


@router.get("/embedding-status")
async def embedding_status():
    from backend.services.embedding import config_status
    return config_status()


@router.get("/vector-stats")
async def vector_stats(current_user: dict = Depends(get_current_user)):
    from backend.services.vector_store import get_vector_store
    vs = get_vector_store()
    vs._ensure_init()
    try:
        total = vs.table.count_rows()
    except Exception:
        total = 0
    return {"total_vectors": total}
