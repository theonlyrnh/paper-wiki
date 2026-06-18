"""Authentication and session management — username-based.

Security features:
- bcrypt password hashing (cost 12)
- Session stored in DB with expiry
- HttpOnly cookie for session ID
- Rate limiting on login (per IP + per username)
- Rate limiting on invitation code (per IP + per code) — anti-brute-force
- Audit logging
"""

import secrets
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Request, Response, HTTPException, Cookie, Depends

from backend.database import get_db

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────
SESSION_COOKIE_NAME = "pw_session"
SESSION_DURATION_HOURS = 24 * 7          # 7 days
SESSION_REFRESH_HOURS = 24               # refresh if <24h left

# Login rate limits
MAX_LOGIN_ATTEMPTS_PER_IP = 10
MAX_LOGIN_ATTEMPTS_PER_USER = 5
LOGIN_WINDOW_MINUTES = 5

# Invitation code brute-force protection
MAX_CODE_ATTEMPTS_PER_IP = 15            # 15 code guesses per IP per window
MAX_CODE_ATTEMPTS_GLOBAL = 30            # 30 total code guesses per window
CODE_WINDOW_MINUTES = 10                 # 10-minute window
CODE_LOCKOUT_MINUTES = 30                # 30-minute lockout after exceeding


# ── Password ───────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ── Session Management ─────────────────────────────────

async def create_session(user_id: int) -> str:
    session_id = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at.isoformat()),
        )
        await db.commit()
    finally:
        await db.close()
    return session_id


async def validate_session(session_id: str) -> Optional[dict]:
    if not session_id:
        return None

    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT s.id as session_id, s.expires_at, s.user_id,
                      u.id, u.username, u.nickname, u.role, u.status,
                      u.can_invite, u.user_config
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.id = ?""",
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()
            return None

        if row["status"] != "active":
            return None

        # Refresh if close to expiry
        hours_left = (expires_at - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left < SESSION_REFRESH_HOURS:
            new_expiry = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
            await db.execute(
                "UPDATE sessions SET expires_at = ?, last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_expiry.isoformat(), session_id),
            )
        else:
            await db.execute(
                "UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
        await db.commit()

        import json
        user_config = {}
        try:
            if row["user_config"]:
                user_config = json.loads(row["user_config"])
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "id": row["id"],
            "username": row["username"],
            "nickname": row["nickname"],
            "role": row["role"],
            "can_invite": bool(row["can_invite"]),
            "config": user_config,
        }
    finally:
        await db.close()


async def delete_session(session_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()
    finally:
        await db.close()


async def delete_all_sessions(user_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()
    finally:
        await db.close()


# ── Rate Limiting (in-memory) ──────────────────────────

_attempts: dict[str, list[float]] = {}


def _check_rate(key: str, max_attempts: int, window_seconds: int) -> bool:
    """Returns True if rate limit exceeded."""
    now = time.time()
    cutoff = now - window_seconds
    attempts = [t for t in _attempts.get(key, []) if t > cutoff]
    _attempts[key] = attempts
    return len(attempts) >= max_attempts


def _record(key: str):
    _attempts.setdefault(key, []).append(time.time())


def check_login_rate_limit(ip: str, username: str):
    if _check_rate(f"login_ip:{ip}", MAX_LOGIN_ATTEMPTS_PER_IP, LOGIN_WINDOW_MINUTES * 60):
        raise HTTPException(429, "登录尝试过于频繁，请几分钟后再试")
    if _check_rate(f"login_user:{username}", MAX_LOGIN_ATTEMPTS_PER_USER, LOGIN_WINDOW_MINUTES * 60):
        raise HTTPException(429, "该账号登录尝试过于频繁，请几分钟后再试")


def record_login_attempt(ip: str, username: str):
    _record(f"login_ip:{ip}")
    _record(f"login_user:{username}")


def check_register_rate_limit(ip: str):
    """Check if registration/code validation is rate-limited."""
    if _check_rate(f"reg_ip:{ip}", MAX_CODE_ATTEMPTS_PER_IP, CODE_WINDOW_MINUTES * 60):
        raise HTTPException(429, f"注册尝试过于频繁，请 {CODE_LOCKOUT_MINUTES} 分钟后再试")
    if _check_rate("reg_global", MAX_CODE_ATTEMPTS_GLOBAL, CODE_WINDOW_MINUTES * 60):
        raise HTTPException(429, "系统注册请求过多，请稍后再试")


def record_register_attempt(ip: str):
    _record(f"reg_ip:{ip}")
    _record("reg_global")


# ── Audit Log ──────────────────────────────────────────

async def log_audit(user_id: Optional[int], action: str, request: Request, metadata: str = None):
    db = await get_db()
    try:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent", "")[:500]
        await db.execute(
            "INSERT INTO audit_log (user_id, action, ip, user_agent, metadata) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, ip, ua, metadata),
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")
    finally:
        await db.close()


# ── FastAPI Dependencies ───────────────────────────────

async def get_current_user(
    request: Request,
    response: Response,
    pw_session: Optional[str] = Cookie(None),
) -> dict:
    session_id = pw_session
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")

    user = await validate_session(session_id)
    if not user:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user


async def get_optional_user(
    request: Request,
    pw_session: Optional[str] = Cookie(None),
) -> Optional[dict]:
    if not pw_session:
        return None
    return await validate_session(pw_session)


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


async def require_can_invite(current_user: dict = Depends(get_current_user)) -> dict:
    """Require user to be admin OR have can_invite permission."""
    if current_user.get("role") != "admin" and not current_user.get("can_invite"):
        raise HTTPException(status_code=403, detail="没有生成邀请码的权限")
    return current_user


# ── Cookie Helpers ─────────────────────────────────────

def set_session_cookie(response: Response, session_id: str, secure: bool = False):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_DURATION_HOURS * 3600,
        path="/",
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
