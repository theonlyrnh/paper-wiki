#!/usr/bin/env python3
"""Regression checks for Paper Wiki search behavior."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.search_engine import WikiSearchEngine, tokenize


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def test_chinese_short_keyword_matches_longer_index_token():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = Path(tmp)
        concepts = wiki_dir / "concepts"
        concepts.mkdir(parents=True)
        (concepts / "multi-fidelity-surrogate-modeling.md").write_text(
            "# 多保真度代理建模\n\n"
            "使用低保真模型快速估算，再用少量高保真数据校正以提升精度。",
            encoding="utf-8",
        )

        engine = WikiSearchEngine()
        engine.build_index_from_dir(wiki_dir)

        results = engine.search("保真", top_k=5, user_id=None)
        names = [r["name"] for r in results]
        assert_true(
            "multi-fidelity-surrogate-modeling" in names,
            f"query '保真' should match documents containing '保真度'; got {names}",
        )


def test_zero_score_results_are_not_returned():
    with tempfile.TemporaryDirectory() as tmp:
        wiki_dir = Path(tmp)
        sources = wiki_dir / "sources"
        sources.mkdir(parents=True)
        (sources / "unrelated.md").write_text(
            "# 无关文档\n\n这个文档不包含目标关键词。",
            encoding="utf-8",
        )

        engine = WikiSearchEngine()
        engine.build_index_from_dir(wiki_dir)

        results = engine.search("fidelity", top_k=5, user_id=None)
        assert_true(results == [], f"unrelated query should return no zero-score rows; got {results}")


def test_existing_tokenization_contract():
    assert_true(tokenize("保真") == ["保真"], f"unexpected tokenize('保真'): {tokenize('保真')}")
    assert_true(tokenize("多保真度") == ["保真度"], f"unexpected tokenize('多保真度'): {tokenize('多保真度')}")


if __name__ == "__main__":
    test_existing_tokenization_contract()
    test_chinese_short_keyword_matches_longer_index_token()
    test_zero_score_results_are_not_returned()
    print("search regression checks passed")
