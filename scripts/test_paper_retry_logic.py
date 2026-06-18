#!/usr/bin/env python3
"""Regression checks for paper retry mode selection."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.routers.papers import _select_retry_mode


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_raises(exc_type, func, message_contains: str):
    try:
        func()
    except exc_type as exc:
        if message_contains not in str(exc):
            raise AssertionError(f"expected error containing {message_contains!r}, got {exc!r}") from exc
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def test_auto_prefers_ingest_when_markdown_exists():
    assert_equal(_select_retry_mode("failed", "auto", True), "ingest", "auto should ingest existing markdown")


def test_auto_parses_when_markdown_missing():
    assert_equal(_select_retry_mode("failed", "auto", False), "parse", "auto should parse when markdown is missing")


def test_done_auto_requires_explicit_mode():
    assert_raises(ValueError, lambda: _select_retry_mode("done", "auto", True), "already done")


def test_explicit_modes_are_respected():
    assert_equal(_select_retry_mode("done", "ingest", True), "ingest", "explicit ingest should be respected")
    assert_equal(_select_retry_mode("failed", "parse", True), "parse", "explicit parse should be respected")


def test_invalid_mode_is_rejected():
    assert_raises(ValueError, lambda: _select_retry_mode("failed", "invalid", True), "Invalid retry mode")


if __name__ == "__main__":
    test_auto_prefers_ingest_when_markdown_exists()
    test_auto_parses_when_markdown_missing()
    test_done_auto_requires_explicit_mode()
    test_explicit_modes_are_respected()
    test_invalid_mode_is_rejected()
    print("paper retry logic checks passed")
