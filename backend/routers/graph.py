"""Knowledge graph API router — per-user isolation."""

from fastapi import APIRouter, Depends
from backend.services.graph_engine import KnowledgeGraph
from backend.auth import get_current_user

router = APIRouter(prefix="/api/graph", tags=["graph"])

_graph = KnowledgeGraph()


@router.get("")
async def get_graph(current_user: dict = Depends(get_current_user)):
    return _graph.get_graph_data(user_id=current_user["id"])


@router.get("/node/{node_id}")
async def get_node(node_id: str, current_user: dict = Depends(get_current_user)):
    return _graph.get_node_neighbors(node_id, user_id=current_user["id"])


@router.get("/insights")
async def get_insights(current_user: dict = Depends(get_current_user)):
    return _graph.get_insights(user_id=current_user["id"])


@router.post("/rebuild")
async def rebuild_graph(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    _graph.build(user_id=uid)
    data = _graph.get_graph_data(user_id=uid)
    return {"message": "Graph rebuilt", "nodes": len(data["nodes"]), "edges": len(data["edges"])}
