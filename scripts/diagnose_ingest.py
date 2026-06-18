#!/usr/bin/env python3
"""Diagnose Paper Wiki ingestion health without exposing secrets."""

from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import CONFIG  # noqa: E402


def _db_path() -> Path:
    return PROJECT_ROOT / CONFIG["storage"]["db_path"]


def _sanitize(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", text)
    text = re.sub(r"https?://[^/\s]+", "https://<host>", text)
    text = re.sub(r"\b[a-zA-Z0-9.-]+\.(?:com|cn|cc|net|org|io|ren)\b", "<host>", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1<redacted>", text)
    return text[:160]


def _print_status_counts(conn: sqlite3.Connection, table: str):
    print(f"\n[{table}] status counts")
    try:
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS c FROM {table} GROUP BY status ORDER BY c DESC"
        ).fetchall()
    except sqlite3.Error as exc:
        print(f"  unavailable: {_sanitize(exc)}")
        return
    if not rows:
        print("  empty")
        return
    for row in rows:
        print(f"  {row['status'] or '<null>'}: {row['c']}")


def _print_error_top(conn: sqlite3.Connection, table: str):
    print(f"\n[{table}] top errors")
    try:
        rows = conn.execute(
            f"""
            SELECT substr(coalesce(error_msg, ''), 1, 160) AS err, COUNT(*) AS c
            FROM {table}
            WHERE coalesce(error_msg, '') <> ''
            GROUP BY err
            ORDER BY c DESC
            LIMIT 10
            """
        ).fetchall()
    except sqlite3.Error as exc:
        print(f"  unavailable: {_sanitize(exc)}")
        return
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['c']}: {_sanitize(row['err'])}")


def _print_sqlite_pragmas(conn: sqlite3.Connection):
    print("\n[sqlite]")
    for name in ("journal_mode", "busy_timeout", "synchronous", "wal_autocheckpoint"):
        try:
            value = conn.execute(f"PRAGMA {name}").fetchone()[0]
        except sqlite3.Error as exc:
            value = f"unavailable: {_sanitize(exc)}"
        print(f"  {name}: {value}")


def _print_schema_checks(conn: sqlite3.Connection):
    print("\n[schema]")
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='wiki_pages'"
    ).fetchone()
    create_sql = row["sql"] if row else ""
    print(f"  wiki_pages exists: {bool(row)}")
    print(f"  wiki_pages global name UNIQUE removed: {'name            TEXT NOT NULL UNIQUE' not in create_sql and 'name TEXT NOT NULL UNIQUE' not in create_sql}")
    print(f"  wiki_pages scoped UNIQUE present: {'UNIQUE(user_id, type, name)' in create_sql.replace(chr(10), ' ')}")

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(ingest_queue)").fetchall()]
    for col in ("error_type", "attempt", "max_attempts", "locked_at", "next_run_at"):
        print(f"  ingest_queue.{col}: {col in cols}")


def _print_stale_counts(conn: sqlite3.Connection, stale_after_seconds: int):
    cutoff = (datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(seconds=stale_after_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    print("\n[stale]")
    print(f"  cutoff: {cutoff}")
    paper_statuses = ("pending", "parsing", "ingesting")
    ingest_statuses = ("queued", "processing", "analyzing", "generating", "writing", "indexing")
    p_marks = ",".join("?" for _ in paper_statuses)
    i_marks = ",".join("?" for _ in ingest_statuses)
    try:
        p_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM papers WHERE status IN ({p_marks}) AND updated_at < ?",
            (*paper_statuses, cutoff),
        ).fetchone()["c"]
        i_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM ingest_queue WHERE status IN ({i_marks}) AND updated_at < ?",
            (*ingest_statuses, cutoff),
        ).fetchone()["c"]
    except sqlite3.Error as exc:
        print(f"  unavailable: {_sanitize(exc)}")
        return
    print(f"  stale papers: {p_count}")
    print(f"  stale ingest tasks: {i_count}")


def _print_duration_summary(conn: sqlite3.Connection):
    print("\n[ingest_queue] duration seconds by status")
    try:
        rows = conn.execute(
            """
            SELECT status,
                   COUNT(*) AS c,
                   ROUND(AVG((julianday(updated_at)-julianday(created_at))*86400), 1) AS avg_s,
                   ROUND(MIN((julianday(updated_at)-julianday(created_at))*86400), 1) AS min_s,
                   ROUND(MAX((julianday(updated_at)-julianday(created_at))*86400), 1) AS max_s
            FROM ingest_queue
            GROUP BY status
            ORDER BY c DESC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        print(f"  unavailable: {_sanitize(exc)}")
        return
    if not rows:
        print("  empty")
        return
    for row in rows:
        print(f"  {row['status']}: count={row['c']} avg={row['avg_s']} min={row['min_s']} max={row['max_s']}")


async def _mark_stale(stale_after_seconds: int):
    from backend.database import init_db
    from backend.services.ingest_maintenance import cleanup_stale_tasks

    await init_db()
    return await cleanup_stale_tasks(stale_after_seconds=stale_after_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mark-stale", action="store_true", help="mark stale in-progress rows as failed")
    parser.add_argument("--stale-after-seconds", type=int, default=1800)
    args = parser.parse_args()

    db_path = _db_path()
    print("Paper Wiki ingestion diagnostics")
    print(f"DB: {db_path}")
    print(f"DB exists: {db_path.exists()}")

    if args.mark_stale:
        result = asyncio.run(_mark_stale(args.stale_after_seconds))
        print(f"Marked stale: papers={result['papers_marked_failed']} ingest_tasks={result['ingest_tasks_marked_failed']}")

    if not db_path.exists():
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _print_sqlite_pragmas(conn)
        _print_schema_checks(conn)
        for table in ("papers", "ingest_queue", "wiki_pages"):
            try:
                count = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            except sqlite3.Error as exc:
                count = f"unavailable: {_sanitize(exc)}"
            print(f"\n[{table}] rows: {count}")
            if table != "wiki_pages":
                _print_status_counts(conn, table)
                _print_error_top(conn, table)
        _print_stale_counts(conn, args.stale_after_seconds)
        _print_duration_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
