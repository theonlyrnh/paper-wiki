"""Migrate existing DB to username-based auth.

Handles:
- email → username column rename
- Creates default admin if missing
- Adds user_id to business tables
- Generates invitation codes
"""

import asyncio
import os
import bcrypt
import aiosqlite
from pathlib import Path
from backend.config import get_storage_path

DB_PATH: Path = get_storage_path("db_path")

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or (
    (_ for _ in ()).throw(RuntimeError(
        "ADMIN_PASSWORD 环境变量未设置，拒绝使用默认密码。请先 export ADMIN_PASSWORD=<strong-password>"
    ))
)
DEFAULT_ADMIN_NICKNAME = "管理员"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


async def migrate():
    if not DB_PATH.exists():
        print("❌ Database does not exist. Start the server first.")
        return

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        # ── Step 1: Ensure users table exists ──────────────────
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        if not await cursor.fetchone():
            print("📦 Creating users table...")
            await db.executescript("""
                CREATE TABLE users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT NOT NULL UNIQUE,
                    password_hash   TEXT NOT NULL,
                    nickname        TEXT,
                    role            TEXT NOT NULL DEFAULT 'user',
                    status          TEXT NOT NULL DEFAULT 'active',
                    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, last_used_at DATETIME
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS invitation_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
                    created_by INTEGER REFERENCES users(id), used_by INTEGER REFERENCES users(id),
                    used_at DATETIME, expires_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                    action TEXT NOT NULL, ip TEXT, user_agent TEXT, metadata TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.commit()
            print("✅ Users, sessions, invitation_codes, audit_log created.")

        # ── Step 2: Rename email → username ────────────────────
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in await cursor.fetchall()}

        if "email" in columns and "username" not in columns:
            print("🔧 Renaming email → username...")
            await db.execute("ALTER TABLE users RENAME COLUMN email TO username")
            await db.commit()
            # Update existing admin: email address → username
            await db.execute(
                "UPDATE users SET username = ? WHERE username LIKE '%@%'",
                (DEFAULT_ADMIN_USERNAME,),
            )
            await db.commit()
            print("✅ Column renamed. Admin username set to 'admin'.")
        elif "email" in columns and "username" in columns:
            # Both exist — copy email to username for rows missing username, then drop email
            print("⚠️  Both email and username columns exist, cleaning up...")
            await db.execute("UPDATE users SET username = email WHERE username IS NULL OR username = ''")
            await db.commit()
            # SQLite doesn't support DROP COLUMN before 3.35.0
            try:
                await db.execute("ALTER TABLE users DROP COLUMN email")
                await db.commit()
                print("✅ Dropped email column.")
            except Exception:
                print("ℹ️  Could not drop email column (old SQLite), leaving it.")

        # Update admin password hash (in case schema changed)
        cursor = await db.execute(
            "SELECT id, username FROM users WHERE username = ?", (DEFAULT_ADMIN_USERNAME,)
        )
        admin = await cursor.fetchone()
        if admin:
            admin_id = admin["id"]
            # Reset password to default
            await db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(DEFAULT_ADMIN_PASSWORD), admin_id),
            )
            await db.commit()
            print(f"ℹ️  Admin '{DEFAULT_ADMIN_USERNAME}' (id={admin_id}), password reset to default.")
        else:
            print(f"👤 Creating admin user '{DEFAULT_ADMIN_USERNAME}'...")
            cursor = await db.execute(
                "INSERT INTO users (username, password_hash, nickname, role, status) VALUES (?, ?, ?, 'admin', 'active')",
                (DEFAULT_ADMIN_USERNAME, hash_password(DEFAULT_ADMIN_PASSWORD), DEFAULT_ADMIN_NICKNAME),
            )
            await db.commit()
            admin_id = cursor.lastrowid
            print(f"✅ Admin created (id={admin_id}).")

        # ── Step 3: Add user_id to business tables ─────────────
        tables = ["papers", "wiki_pages", "chat_sessions", "ingest_queue"]
        for table in tables:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            )
            if not await cursor.fetchone():
                print(f"⏭️  Table {table} does not exist, skipping.")
                continue

            cursor = await db.execute(f"PRAGMA table_info({table})")
            cols = {row["name"] for row in await cursor.fetchall()}

            if "user_id" not in cols:
                print(f"🔧 Adding user_id to {table}...")
                await db.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)")
                await db.commit()

            cursor = await db.execute(f"SELECT COUNT(*) as c FROM {table} WHERE user_id IS NULL")
            null_count = (await cursor.fetchone())["c"]
            if null_count > 0:
                print(f"📎 Binding {null_count} rows in {table} to admin (id={admin_id})...")
                await db.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (admin_id,))
                await db.commit()
                print(f"   ✅ Done.")

        # ── Step 4: Generate invitation codes ──────────────────
        cursor = await db.execute("SELECT COUNT(*) as c FROM invitation_codes")
        code_count = (await cursor.fetchone())["c"]
        if code_count == 0:
            import secrets
            codes = [f"PW-{secrets.token_hex(4).upper()}" for _ in range(3)]
            for code in codes:
                await db.execute(
                    "INSERT INTO invitation_codes (code, created_by) VALUES (?, ?)",
                    (code, admin_id),
                )
            await db.commit()
            print(f"🎟️  Invitation codes: {', '.join(codes)}")
        else:
            print(f"ℹ️  {code_count} invitation codes already exist.")

        print("\n✅ Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
