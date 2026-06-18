#!/usr/bin/env python3
"""Integration check for DELETE /api/papers/{id}/raw-pdf."""

from __future__ import annotations

import asyncio
import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


async def _setup_user_and_paper(db, *, user_id: int, paper_id: str, md_path: Path):
    await db.execute(
        "INSERT INTO users (id, username, password_hash, role, status) VALUES (?, ?, ?, 'user', 'active')",
        (user_id, "rawpdf-test", "hash"),
    )
    await db.execute(
        """INSERT INTO papers (id, user_id, title, filename, file_hash, status, markdown_path)
           VALUES (?, ?, ?, ?, ?, 'done', ?)""",
        (paper_id, user_id, "FlashAttention", "paper.pdf", "hash", str(md_path)),
    )
    await db.commit()


async def main():
    import backend.auth as auth
    import backend.database as database
    import backend.routers.papers as papers_router
    import backend.services.storage_quota as storage_quota
    from backend.main import app
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "papers.db"
        raw_dir = base / "raw"
        user_dir = raw_dir / "7"
        user_dir.mkdir(parents=True)
        pdf_path = user_dir / "paper.pdf"
        md_path = user_dir / "paper.md"
        pdf_path.write_bytes(b"%PDF-raw-test")
        md_path.write_text("# FlashAttention\n\nParsed markdown.", encoding="utf-8")

        original_db_path = database.DB_PATH
        original_raw_papers = papers_router.RAW_DIR
        original_raw_quota = storage_quota.RAW_DIR
        original_get_current_user = papers_router.get_current_user
        try:
            database.DB_PATH = db_path
            papers_router.RAW_DIR = raw_dir
            storage_quota.RAW_DIR = raw_dir
            await database.init_db()
            db = await database.get_db()
            try:
                await _setup_user_and_paper(db, user_id=7, paper_id="paper-1", md_path=md_path)
            finally:
                await db.close()

            async def fake_current_user():
                return {"id": 7, "username": "rawpdf-test", "role": "user"}

            app.dependency_overrides[auth.get_current_user] = fake_current_user
            app.dependency_overrides[papers_router.get_current_user] = fake_current_user
            client = TestClient(app)
            response = client.delete("/api/papers/paper-1/raw-pdf?ensure_cache=false")
            assert_true(response.status_code == 200, f"unexpected status: {response.status_code} {response.text}")
            data = response.json()
            assert_true(data["deleted"] is True, "API should report deleted")
            assert_true(not pdf_path.exists(), "raw PDF should be deleted")
            assert_true(md_path.exists(), "markdown should remain")
            assert_true(data["quota"]["used_bytes"] == 0, f"quota should refresh after delete: {data['quota']}")
        finally:
            app.dependency_overrides.clear()
            database.DB_PATH = original_db_path
            papers_router.RAW_DIR = original_raw_papers
            storage_quota.RAW_DIR = original_raw_quota
            papers_router.get_current_user = original_get_current_user


if __name__ == "__main__":
    asyncio.run(main())
    print("raw PDF delete API checks passed")
