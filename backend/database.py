"""SQLite database initialization and connection management."""

import aiosqlite
from pathlib import Path
from backend.config import get_storage_path

DB_PATH: Path = get_storage_path("db_path")

SCHEMA_SQL = """
-- 用户表 (用户名登录)
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    nickname        TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    can_invite      INTEGER NOT NULL DEFAULT 0,
    user_config     TEXT DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    expires_at      DATETIME NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at    DATETIME
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- 邀请码表
CREATE TABLE IF NOT EXISTS invitation_codes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL UNIQUE,
    created_by      INTEGER REFERENCES users(id),
    used_by         INTEGER REFERENCES users(id),
    used_at         DATETIME,
    expires_at      DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 审计日志表
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    action          TEXT NOT NULL,
    ip              TEXT,
    user_agent      TEXT,
    metadata        TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

-- 论文表
CREATE TABLE IF NOT EXISTS papers (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_hash       TEXT,
    authors         TEXT,
    year            INTEGER,
    tags            TEXT,
    status          TEXT DEFAULT 'pending',
    error_msg       TEXT,
    markdown_path   TEXT,
    wiki_source_path TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_papers_user_id ON papers(user_id);

-- Wiki 页面表
CREATE TABLE IF NOT EXISTS wiki_pages (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    path            TEXT NOT NULL,
    title           TEXT,
    sources         TEXT,
    tags            TEXT,
    content_hash    TEXT,
    indexed_hash    TEXT,
    indexed_at      DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, type, name)
);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_user_id ON wiki_pages(user_id);

-- 对话表
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    title           TEXT DEFAULT '新对话',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    "references"    TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 摄入队列表
CREATE TABLE IF NOT EXISTS ingest_queue (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    paper_id        TEXT NOT NULL REFERENCES papers(id),
    task_type       TEXT DEFAULT 'ingest',
    status          TEXT DEFAULT 'queued',
    step            TEXT,
    attempt         INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 3,
    retry_count     INTEGER DEFAULT 0,
    next_run_at     DATETIME,
    locked_at       DATETIME,
    locked_by       TEXT,
    heartbeat_at    DATETIME,
    error_type      TEXT,
    error_msg       TEXT,
    payload_json    TEXT,
    result_json     TEXT,
    stage_started_at DATETIME,
    stage_duration_ms INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ingest_queue_user_id ON ingest_queue(user_id);
"""


async def _configure_connection(db: aiosqlite.Connection, *, init: bool = False):
    """Apply SQLite pragmas used by all runtime connections."""
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=30000")
    await db.execute("PRAGMA synchronous=NORMAL")
    if init:
        await db.execute("PRAGMA journal_mode=WAL")


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return await cursor.fetchone() is not None


async def _table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cursor.fetchall()}


async def _has_unique_index(db: aiosqlite.Connection, table: str, columns: list[str]) -> bool:
    cursor = await db.execute(f"PRAGMA index_list({table})")
    for row in await cursor.fetchall():
        index_name = row[1]
        is_unique = bool(row[2])
        if not is_unique:
            continue
        info = await db.execute(f"PRAGMA index_info({index_name})")
        indexed_columns = [col[2] for col in await info.fetchall()]
        if indexed_columns == columns:
            return True
    return False


async def _add_column_if_missing(db: aiosqlite.Connection, table: str, column: str, definition: str):
    columns = await _table_columns(db, table)
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def migrate_wiki_pages_schema(db: aiosqlite.Connection):
    """Migrate wiki_pages from global name uniqueness to user/type/name uniqueness.

    Early project databases used ``name TEXT NOT NULL UNIQUE``. That breaks
    multi-user data isolation and also prevents an entity and a concept from
    sharing the same filename. Rebuild the table idempotently when the expected
    unique constraint is missing.
    """
    if not await _table_exists(db, "wiki_pages"):
        return

    if await _has_unique_index(db, "wiki_pages", ["user_id", "type", "name"]):
        await _add_column_if_missing(db, "wiki_pages", "indexed_hash", "TEXT")
        await _add_column_if_missing(db, "wiki_pages", "indexed_at", "DATETIME")
        await db.commit()
        return

    columns = await _table_columns(db, "wiki_pages")
    select_content_hash = "content_hash" if "content_hash" in columns else "NULL"
    select_indexed_hash = "indexed_hash" if "indexed_hash" in columns else "NULL"
    select_indexed_at = "indexed_at" if "indexed_at" in columns else "NULL"
    select_created_at = "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP"
    select_updated_at = "updated_at" if "updated_at" in columns else "CURRENT_TIMESTAMP"
    select_user_id = (
        "COALESCE(user_id, (SELECT id FROM users ORDER BY id LIMIT 1), 1)"
        if "user_id" in columns else
        "COALESCE((SELECT id FROM users ORDER BY id LIMIT 1), 1)"
    )

    await db.commit()
    await db.execute("PRAGMA foreign_keys=OFF")
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_pages_new (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER NOT NULL REFERENCES users(id),
            name            TEXT NOT NULL,
            type            TEXT NOT NULL,
            path            TEXT NOT NULL,
            title           TEXT,
            sources         TEXT,
            tags            TEXT,
            content_hash    TEXT,
            indexed_hash    TEXT,
            indexed_at      DATETIME,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, type, name)
        )
        """
    )
    await db.execute(
        f"""
        INSERT OR IGNORE INTO wiki_pages_new (
            id, user_id, name, type, path, title, sources, tags,
            content_hash, indexed_hash, indexed_at, created_at, updated_at
        )
        SELECT
            id, {select_user_id}, name, type, path, title, sources, tags,
            {select_content_hash}, {select_indexed_hash}, {select_indexed_at},
            {select_created_at}, {select_updated_at}
        FROM wiki_pages
        """
    )
    await db.execute("DROP TABLE wiki_pages")
    await db.execute("ALTER TABLE wiki_pages_new RENAME TO wiki_pages")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_user_id ON wiki_pages(user_id)")
    await db.commit()
    await db.execute("PRAGMA foreign_keys=ON")


async def migrate_ingest_queue_schema(db: aiosqlite.Connection):
    """Add lightweight queue/diagnostic columns used by the hardened ingestion path."""
    if not await _table_exists(db, "ingest_queue"):
        return

    additions = {
        "task_type": "TEXT DEFAULT 'ingest'",
        "attempt": "INTEGER DEFAULT 0",
        "max_attempts": "INTEGER DEFAULT 3",
        "next_run_at": "DATETIME",
        "locked_at": "DATETIME",
        "locked_by": "TEXT",
        "heartbeat_at": "DATETIME",
        "error_type": "TEXT",
        "payload_json": "TEXT",
        "result_json": "TEXT",
        "stage_started_at": "DATETIME",
        "stage_duration_ms": "INTEGER DEFAULT 0",
    }
    for column, definition in additions.items():
        await _add_column_if_missing(db, "ingest_queue", column, definition)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_queue_status_next_run ON ingest_queue(status, next_run_at, created_at)"
    )
    await db.commit()


async def init_db():
    """Initialize the database and create tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await _configure_connection(db, init=True)
        await db.executescript(SCHEMA_SQL)
        # executescript may reset connection-level PRAGMAs, re-apply
        await _configure_connection(db, init=True)
        await migrate_wiki_pages_schema(db)
        await migrate_ingest_queue_schema(db)
        # Create indexes that depend on migrated columns AFTER migration
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingest_queue_status_next_run "
            "ON ingest_queue(status, next_run_at, created_at)"
        )
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await _configure_connection(db)
    return db
