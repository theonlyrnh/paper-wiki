"""Pydantic data models for the Paper Wiki API."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# === Paper Models ===

class PaperUploadResponse(BaseModel):
    id: str
    title: str
    filename: str
    status: str
    message: str


class PaperRetryResponse(BaseModel):
    id: str
    mode: str
    status: str
    message: str


class PaperListItem(BaseModel):
    id: str
    title: str
    filename: str
    authors: Optional[str] = None
    year: Optional[int] = None
    tags: Optional[list[str]] = None
    status: str
    created_at: str
    updated_at: str
    raw_pdf_available: bool = False
    raw_pdf_size_mb: float = 0


class PaperDetail(PaperListItem):
    file_hash: Optional[str] = None
    error_msg: Optional[str] = None
    markdown_path: Optional[str] = None
    wiki_source_path: Optional[str] = None
    markdown_content: Optional[str] = None
    raw_pdf_available: bool = False
    raw_pdf_size: int = 0
    raw_pdf_size_mb: float = 0


# === Ingest Models ===

class IngestStatusItem(BaseModel):
    id: str
    paper_id: str
    paper_title: Optional[str] = None
    status: str
    step: Optional[str] = None
    retry_count: int = 0
    error_msg: Optional[str] = None
    created_at: str
    updated_at: str


# === Wiki Models ===

class WikiPage(BaseModel):
    id: str
    name: str
    type: str
    path: str
    title: Optional[str] = None
    sources: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    content: Optional[str] = None
    created_at: str
    updated_at: str


# === Graph Models ===

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    community: int = 0
    degree: int = 0
    size: float = 1.0


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float = 1.0
    signal: str = "direct_link"


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    communities: dict = Field(default_factory=dict)


# === Stats ===

class StatsResponse(BaseModel):
    paper_count: int
    wiki_page_count: int
    graph_node_count: int
    graph_edge_count: int
    ingest_queue_size: int


# === Health ===

class HealthResponse(BaseModel):
    status: str
    mineru_status: str
    version: str = "0.1.0"
