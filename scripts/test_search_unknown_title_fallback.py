#!/usr/bin/env python3
"""Regression checks for search result titles when LLM generated Unknown wiki titles."""

from __future__ import annotations

import asyncio
import json
import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    def __aiter__(self):
        self._iter = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeDB:
    def __init__(self):
        self.closed = False

    async def execute(self, sql, params=()):
        if "FROM wiki_pages" in sql:
            return FakeCursor([
                {"name": "flash-attention-online-softmax", "title": "Unknown", "sources": json.dumps(["paper-1"])},
            ])
        if "FROM papers" in sql:
            return FakeCursor([
                {"id": "paper-1", "title": "FlashAttention: Fast and Memory-Efficient Exact Attention"},
            ])
        return FakeCursor([])

    async def close(self):
        self.closed = True


async def test_unknown_search_title_uses_source_paper_title():
    import backend.routers.search as search_router

    async def fake_get_db():
        return FakeDB()

    original_get_db = search_router.get_db
    search_router.get_db = fake_get_db
    try:
        results = [{
            "name": "flash-attention-online-softmax",
            "title": "Unknown",
            "type": "source",
            "snippet": "# Unknown 提出在线计算 softmax 归一化因子的方法",
            "score": 2.0,
        }]
        await search_router._enrich_results(results, user_id=7)
    finally:
        search_router.get_db = original_get_db

    assert_equal(
        results[0]["title"],
        "FlashAttention: Fast and Memory-Efficient Exact Attention",
        "Unknown search result title should fall back to the source paper title",
    )
    assert_equal(
        results[0]["papers"][0]["title"],
        "FlashAttention: Fast and Memory-Efficient Exact Attention",
        "source paper enrichment should remain available",
    )


def test_search_engine_ignores_unknown_heading_when_filename_is_better():
    from backend.services.search_engine import WikiSearchEngine

    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = Path(tmp)
        sources = wiki_dir / "sources"
        sources.mkdir(parents=True)
        (sources / "flash-attention-online-softmax.md").write_text(
            "# Unknown\n\nFlashAttention uses online softmax for fast exact attention.",
            encoding="utf-8",
        )

        engine = WikiSearchEngine()
        engine.build_index_from_dir(wiki_dir)
        results = engine.search("flashattention", top_k=5)

    assert_equal(
        results[0]["title"],
        "Flash Attention Online Softmax",
        "BM25 should avoid showing literal Unknown when filename provides a better title",
    )


if __name__ == "__main__":
    asyncio.run(test_unknown_search_title_uses_source_paper_title())
    test_search_engine_ignores_unknown_heading_when_filename_is_better()
    print("search unknown title fallback checks passed")
