"""System health and stats API — per-user stats when authenticated."""

import json
from fastapi import APIRouter, Depends
from backend.database import get_db
from backend.models import HealthResponse, StatsResponse
from backend.auth import get_optional_user, get_current_user
from backend.services.graph_engine import KnowledgeGraph
from backend.services.storage_quota import quota_status_for_user

router = APIRouter(tags=["system"])

_graph = KnowledgeGraph()


@router.get("/api/health", response_model=HealthResponse)
async def health():
    """Public health check — no auth required."""
    return HealthResponse(status="ok", mineru_status="ok", version="0.1.0")


@router.get("/api/stats", response_model=StatsResponse)
async def stats(current_user=Depends(get_optional_user)):
    """Per-user stats. Returns zeros if not authenticated."""
    db = await get_db()
    try:
        if current_user:
            uid = current_user["id"]
            paper_count = (await (await db.execute(
                "SELECT COUNT(*) as c FROM papers WHERE user_id = ?", (uid,))).fetchone())["c"]
            wiki_count = (await (await db.execute(
                "SELECT COUNT(*) as c FROM wiki_pages WHERE user_id = ?", (uid,))).fetchone())["c"]
            queue_size = (await (await db.execute(
                "SELECT COUNT(*) as c FROM ingest_queue WHERE user_id = ? AND status IN ('queued','processing')", (uid,)
            )).fetchone())["c"]

            # Graph stats (build per-user graph if needed)
            try:
                graph_data = _graph.get_graph_data(user_id=uid)
                graph_nodes = len(graph_data["nodes"])
                graph_edges = len(graph_data["edges"])
            except Exception:
                graph_nodes = 0
                graph_edges = 0
        else:
            paper_count = wiki_count = queue_size = 0
            graph_nodes = graph_edges = 0

        return StatsResponse(
            paper_count=paper_count,
            wiki_page_count=wiki_count,
            graph_node_count=graph_nodes,
            graph_edge_count=graph_edges,
            ingest_queue_size=queue_size,
        )
    finally:
        await db.close()


@router.get("/api/storage/quota")
async def storage_quota(current_user: dict = Depends(get_current_user)):
    """Return current user's raw PDF quota usage and cleanup preference."""
    db = await get_db()
    cfg = {}
    try:
        row = await (await db.execute(
            "SELECT user_config FROM users WHERE id = ?", (current_user["id"],)
        )).fetchone()
        cfg = json.loads(row["user_config"]) if row and row["user_config"] else {}
    finally:
        await db.close()

    status = quota_status_for_user(current_user["id"])
    status["manual_delete_available"] = True
    return status
