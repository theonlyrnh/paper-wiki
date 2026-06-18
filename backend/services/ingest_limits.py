"""Shared concurrency limiters for long-running ingestion work."""

from __future__ import annotations

import asyncio

from backend.config import CONFIG

INGEST_CONFIG = CONFIG.get("ingest", {}) if isinstance(CONFIG.get("ingest", {}), dict) else {}


def _positive_int(value, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


PARSE_MAX_CONCURRENCY = _positive_int(INGEST_CONFIG.get("parse_max_concurrency"), 1)
INGEST_MAX_CONCURRENCY = _positive_int(
    INGEST_CONFIG.get("max_concurrency", INGEST_CONFIG.get("llm_max_concurrency")),
    1,
)
EMBEDDING_MAX_CONCURRENCY = _positive_int(INGEST_CONFIG.get("embedding_max_concurrency"), 2)

parse_semaphore = asyncio.Semaphore(PARSE_MAX_CONCURRENCY)
ingest_semaphore = asyncio.Semaphore(INGEST_MAX_CONCURRENCY)
embedding_semaphore = asyncio.Semaphore(EMBEDDING_MAX_CONCURRENCY)
