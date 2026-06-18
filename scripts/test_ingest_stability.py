#!/usr/bin/env python3
"""Regression checks for ingestion stability hardening."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def assert_raises(exc_type, func, message_contains: str = ""):
    try:
        func()
    except exc_type as exc:
        if message_contains and message_contains not in str(exc):
            raise AssertionError(f"expected error containing {message_contains!r}, got {exc!r}") from exc
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def test_llm_json_parser_accepts_fenced_json():
    from backend.services.llm_client import parse_llm_json_response

    parsed = parse_llm_json_response('```json\n{"title":"Paper","tags":["a"]}\n```', stage="analysis")

    assert_equal(parsed["title"], "Paper", "fenced JSON should parse")
    assert_equal(parsed["tags"], ["a"], "array fields should survive parsing")


def test_llm_json_parser_rejects_invalid_without_unknown_fallback():
    from backend.services.llm_client import LLMJSONParseError, parse_llm_json_response

    logger = logging.getLogger("backend.services.llm_client")
    original_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        assert_raises(
            LLMJSONParseError,
            lambda: parse_llm_json_response("not json at all", stage="analysis"),
            "analysis",
        )
    finally:
        logger.setLevel(original_level)


def test_retryable_llm_status_classification():
    from backend.services.llm_client import is_retryable_llm_status

    for code in (408, 409, 429, 500, 502, 503, 504):
        assert_true(is_retryable_llm_status(code), f"HTTP {code} should be retryable")

    for code in (400, 401, 403, 404, 422):
        assert_true(not is_retryable_llm_status(code), f"HTTP {code} should not be retryable")


def test_index_addition_accepts_singular_and_plural_fields():
    from backend.services.ingest_pipeline import _extract_index_addition

    assert_equal(
        _extract_index_addition({"index_addition": "singular"}),
        "singular",
        "singular field should be accepted",
    )
    assert_equal(
        _extract_index_addition({"index_additions": "plural"}),
        "plural",
        "plural field should be accepted for prompt compatibility",
    )


async def _run_wiki_pages_schema_migration_check(db_path: Path):
    import aiosqlite
    from backend.database import migrate_wiki_pages_schema

    async with aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            INSERT INTO users (id, username, password_hash) VALUES (1, 'u1', 'x'), (2, 'u2', 'x');
            CREATE TABLE wiki_pages (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                path TEXT NOT NULL,
                title TEXT,
                sources TEXT,
                tags TEXT,
                content_hash TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id)
            );
            INSERT INTO wiki_pages (id, user_id, name, type, path)
            VALUES ('p1', 1, 'attention.md', 'entity', '/tmp/attention.md');
            """
        )
        await db.commit()

        await migrate_wiki_pages_schema(db)

        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='wiki_pages'")
        create_sql = (await cursor.fetchone())[0]
        assert_true(
            "name TEXT NOT NULL UNIQUE" not in create_sql,
            "old global name uniqueness should be removed",
        )

        await db.execute(
            "INSERT INTO wiki_pages (id, user_id, name, type, path) VALUES (?, ?, ?, ?, ?)",
            ("p2", 2, "attention.md", "entity", "/tmp/attention-user2.md"),
        )
        await db.execute(
            "INSERT INTO wiki_pages (id, user_id, name, type, path) VALUES (?, ?, ?, ?, ?)",
            ("p3", 1, "attention.md", "concept", "/tmp/attention-concept.md"),
        )
        await db.commit()

        duplicate_failed = False
        try:
            await db.execute(
                "INSERT INTO wiki_pages (id, user_id, name, type, path) VALUES (?, ?, ?, ?, ?)",
                ("p4", 1, "attention.md", "entity", "/tmp/dup.md"),
            )
            await db.commit()
        except sqlite3.IntegrityError:
            duplicate_failed = True
        assert_true(
            duplicate_failed,
            "same user/type/name should remain unique after migration",
        )


def test_wiki_pages_schema_migration_scopes_name_by_user_and_type():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_wiki_pages_schema_migration_check(Path(tmp) / "papers.db"))


async def _run_stale_cleanup_check(db_path: Path):
    import aiosqlite
    from backend.services.ingest_maintenance import cleanup_stale_tasks

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(
            """
            CREATE TABLE papers (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                status TEXT,
                error_msg TEXT,
                updated_at DATETIME
            );
            CREATE TABLE ingest_queue (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                paper_id TEXT,
                status TEXT,
                step TEXT,
                error_type TEXT,
                error_msg TEXT,
                updated_at DATETIME
            );
            INSERT INTO papers (id, user_id, status, updated_at)
            VALUES
              ('old-parse', 1, 'parsing', '2026-06-17 10:00:00'),
              ('recent-parse', 1, 'parsing', '2026-06-17 11:55:00'),
              ('done-paper', 1, 'done', '2026-06-17 09:00:00');
            INSERT INTO ingest_queue (id, user_id, paper_id, status, step, updated_at)
            VALUES
              ('old-ingest', 1, 'old-parse', 'analyzing', 'analyzing', '2026-06-17 10:00:00'),
              ('recent-ingest', 1, 'recent-parse', 'analyzing', 'analyzing', '2026-06-17 11:55:00');
            """
        )
        await db.commit()

        result = await cleanup_stale_tasks(
            db=db,
            stale_after_seconds=1800,
            now="2026-06-17 12:00:00",
        )

        assert_equal(result["papers_marked_failed"], 1, "one old paper should be marked failed")
        assert_equal(result["ingest_tasks_marked_failed"], 1, "one old ingest task should be marked failed")

        cursor = await db.execute("SELECT status, error_msg FROM papers WHERE id = 'old-parse'")
        old_paper = await cursor.fetchone()
        assert_equal(old_paper["status"], "failed", "old parsing paper should become failed")
        assert_true("stale" in old_paper["error_msg"], "old paper should explain stale failure")

        cursor = await db.execute("SELECT status FROM papers WHERE id = 'recent-parse'")
        recent_paper = await cursor.fetchone()
        assert_equal(recent_paper["status"], "parsing", "recent parsing paper should stay active")

        cursor = await db.execute("SELECT status, error_type FROM ingest_queue WHERE id = 'old-ingest'")
        old_task = await cursor.fetchone()
        assert_equal(old_task["status"], "failed", "old ingest task should become failed")
        assert_equal(old_task["error_type"], "stale_task", "old ingest task should have stale error type")


def test_stale_cleanup_marks_only_old_in_progress_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_stale_cleanup_check(Path(tmp) / "papers.db"))


if __name__ == "__main__":
    test_llm_json_parser_accepts_fenced_json()
    test_llm_json_parser_rejects_invalid_without_unknown_fallback()
    test_retryable_llm_status_classification()
    test_index_addition_accepts_singular_and_plural_fields()
    test_wiki_pages_schema_migration_scopes_name_by_user_and_type()
    test_stale_cleanup_marks_only_old_in_progress_tasks()
    print("ingest stability checks passed")
