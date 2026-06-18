#!/usr/bin/env python3
"""Regression checks for per-user raw PDF storage quota."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.storage_quota import (  # noqa: E402
    RAW_PDF_QUOTA_MB,
    quota_status_from_dir,
    ensure_upload_fits_quota,
    is_cleanup_candidate,
)


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def assert_raises_quota(func):
    try:
        func()
    except ValueError as exc:
        assert_true("上传文件空间已满" in str(exc) or "超过您的" in str(exc), f"unexpected error: {exc}")
        return
    raise AssertionError("expected ValueError for quota overflow")


def test_default_quota_is_1000mb():
    assert_equal(RAW_PDF_QUOTA_MB, 1000, "default raw PDF quota should be 1000MB")


def test_quota_status_counts_only_pdf_files_for_user_dir():
    with tempfile.TemporaryDirectory() as tmp:
        user_dir = Path(tmp)
        (user_dir / "a.pdf").write_bytes(b"a" * 1024)
        (user_dir / "b.PDF").write_bytes(b"b" * 2048)
        (user_dir / "notes.md").write_bytes(b"not counted" * 100)

        status = quota_status_from_dir(user_dir, quota_mb=1)

        assert_equal(status["used_bytes"], 3072, "only pdf bytes should count")
        assert_equal(status["quota_bytes"], 1024 * 1024, "quota bytes should be MB based")
        assert_equal(status["used_mb"], 0.003, "used MB should be rounded for UI")
        assert_equal(status["quota_mb"], 1, "quota MB should be reported")
        assert_true(status["usage_percent"] > 0, "usage percent should be positive")
        assert_true(status["can_upload"], "small usage should allow uploads")


def test_upload_that_would_exceed_quota_is_rejected():
    status = {
        "used_bytes": 900 * 1024 * 1024,
        "quota_bytes": 1000 * 1024 * 1024,
    }
    assert_raises_quota(lambda: ensure_upload_fits_quota(status, 120 * 1024 * 1024))


def test_upload_within_quota_is_allowed():
    status = {
        "used_bytes": 900 * 1024 * 1024,
        "quota_bytes": 1000 * 1024 * 1024,
    }
    ensure_upload_fits_quota(status, 50 * 1024 * 1024)


def test_cleanup_candidate_requires_done_markdown_and_age():
    from datetime import datetime

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pdf = base / "paper.pdf"
        md = base / "paper.md"
        pdf.write_bytes(b"pdf")
        md.write_text("# parsed", encoding="utf-8")
        now = datetime(2026, 6, 17, 12, 0, 0)
        old_done = {
            "status": "done",
            "markdown_path": str(md),
            "updated_at": "2026-06-01 12:00:00",
        }
        recent_done = {
            "status": "done",
            "markdown_path": str(md),
            "updated_at": "2026-06-16 12:00:00",
        }
        failed = {
            "status": "failed",
            "markdown_path": str(md),
            "updated_at": "2026-06-01 12:00:00",
        }

        assert_true(is_cleanup_candidate(old_done, pdf, now=now, retention_days=7), "old parsed PDF should be cleanable")
        assert_true(not is_cleanup_candidate(recent_done, pdf, now=now, retention_days=7), "recent PDF should not be cleanable")
        assert_true(not is_cleanup_candidate(failed, pdf, now=now, retention_days=7), "failed paper should not be cleanable")


if __name__ == "__main__":
    test_default_quota_is_1000mb()
    test_quota_status_counts_only_pdf_files_for_user_dir()
    test_upload_that_would_exceed_quota_is_rejected()
    test_upload_within_quota_is_allowed()
    test_cleanup_candidate_requires_done_markdown_and_age()
    print("storage quota checks passed")
