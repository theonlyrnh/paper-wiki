#!/usr/bin/env python3
"""Regression checks for PDF evidence cache and raw PDF deletion lifecycle."""

from __future__ import annotations

import base64
import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def test_evidence_cache_roundtrip_survives_raw_pdf_deletion():
    from backend.services.evidence_cache import (
        build_highlight_cache_key,
        cache_slices,
        get_cached_slices,
    )

    with tempfile.TemporaryDirectory() as tmp:
        cache_root = Path(tmp)
        snippets = [{"text": "FlashAttention uses online softmax.", "start_line": 3, "end_line": 8}]
        cache_key = build_highlight_cache_key("flashattention", snippets)
        source_image = b"fake-jpeg-bytes"
        slices = [{
            "page": 1,
            "total_pages": 12,
            "image": "data:image/jpeg;base64," + base64.b64encode(source_image).decode(),
            "text": "FlashAttention uses online softmax.",
            "score": 99,
        }]

        cached = cache_slices(
            cache_root=cache_root,
            user_id=7,
            paper_id="paper-1",
            paper_title="FlashAttention",
            filename="flashattention.pdf",
            cache_key=cache_key,
            slices=slices,
        )

        assert_equal(cached["cache_status"], "stored", "cache_slices should report stored status")
        assert_true(cached["slices"][0]["image"].startswith("data:image/jpeg;base64,"), "stored slice should keep data URL")

        # Simulates raw PDF deletion: cache lookup must not depend on original PDF.
        loaded = get_cached_slices(cache_root=cache_root, user_id=7, paper_id="paper-1", cache_key=cache_key)
        assert_equal(loaded["cache_status"], "hit", "cache should be readable after raw PDF deletion")
        assert_equal(loaded["slices"][0]["text"], "FlashAttention uses online softmax.", "cached slice text should roundtrip")
        assert_equal(base64.b64decode(loaded["slices"][0]["image"].split(",", 1)[1]), source_image, "cached image should roundtrip")


def test_raw_pdf_delete_requires_done_markdown_and_deletes_only_pdf():
    from backend.services.raw_pdf_lifecycle import can_delete_raw_pdf, delete_raw_pdf_file

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pdf = base / "paper.pdf"
        md = base / "paper.md"
        pdf.write_bytes(b"%PDF-raw")
        md.write_text("# Parsed", encoding="utf-8")
        row = {"status": "done", "markdown_path": str(md)}

        allowed, reason = can_delete_raw_pdf(row, pdf)
        assert_true(allowed, f"done paper with markdown and raw PDF should be deletable: {reason}")

        result = delete_raw_pdf_file(pdf)
        assert_true(result["deleted"], "raw PDF should be deleted")
        assert_true(not pdf.exists(), "raw PDF file should be gone")
        assert_true(md.exists(), "markdown file must be kept")
        assert_equal(result["freed_bytes"], len(b"%PDF-raw"), "freed bytes should equal deleted PDF size")


def test_raw_pdf_delete_rejects_failed_paper():
    from backend.services.raw_pdf_lifecycle import can_delete_raw_pdf

    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "paper.pdf"
        pdf.write_bytes(b"%PDF-raw")
        allowed, reason = can_delete_raw_pdf({"status": "failed", "markdown_path": None}, pdf)
        assert_true(not allowed, "failed/unparsed paper should not allow raw PDF deletion")
        assert_true("解析完成" in reason, f"unexpected rejection reason: {reason}")


if __name__ == "__main__":
    test_evidence_cache_roundtrip_survives_raw_pdf_deletion()
    test_raw_pdf_delete_requires_done_markdown_and_deletes_only_pdf()
    test_raw_pdf_delete_rejects_failed_paper()
    print("evidence cache and raw PDF delete checks passed")
