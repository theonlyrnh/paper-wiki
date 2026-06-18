"""Authentication router — username login, invite-code register,
admin management, permission delegation, password reset."""

import re
import ipaddress
import secrets
import logging
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Response, Depends, HTTPException

from backend.database import get_db
from backend.auth import (
    hash_password, verify_password,
    create_session, delete_session, delete_all_sessions,
    get_current_user, require_admin, require_can_invite, log_audit,
    set_session_cookie, clear_session_cookie,
    check_login_rate_limit, record_login_attempt,
    check_register_rate_limit, record_register_attempt,
)
from backend.models import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

USERNAME_RE = re.compile(r'^[\w\u4e00-\u9fff]{2,30}$')


def _is_ssrf_blocked(url: str) -> bool:
    """Return True if the URL resolves to a private/reserved address."""
    try:
        host = urlparse(url).hostname or ""
        if not host:
            return True
        try:
            return not ipaddress.ip_address(host).is_global
        except ValueError:
            pass
        for info in socket.getaddrinfo(host, None):
            if not ipaddress.ip_address(info[4][0]).is_global:
                return True
    except Exception:
        pass
    return False


# ── Models ─────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=6, max_length=128)
    invitation_code: str
    nickname: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


class ResetPasswordRequest(BaseModel):
    """Admin-initiated password reset for a user."""
    new_password: str = Field(..., min_length=6, max_length=128)


class CreateInvitationRequest(BaseModel):
    count: int = 1
    expires_days: int = 30


class AdminUpdateUserRequest(BaseModel):
    nickname: str | None = None
    role: str | None = None
    status: str | None = None
    can_invite: bool | None = None
    new_password: str | None = None


# ── Public ─────────────────────────────────────────────

@router.get("/check-username")
async def check_username(username: str):
    username = username.strip()
    if not USERNAME_RE.match(username):
        return {"available": False, "reason": "用户名需 2-30 字符，支持字母、数字、下划线、中文"}
    db = await get_db()
    try:
        if await (await db.execute("SELECT id FROM users WHERE username = ?", (username,))).fetchone():
            return {"available": False, "reason": "用户名已被使用"}
        return {"available": True}
    finally:
        await db.close()


@router.post("/register")
async def register(req: RegisterRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    username = req.username.strip()

    check_register_rate_limit(ip)

    if not USERNAME_RE.match(username):
        raise HTTPException(400, "用户名格式不正确")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少 6 位")

    db = await get_db()
    try:
        if await (await db.execute("SELECT id FROM users WHERE username = ?", (username,))).fetchone():
            raise HTTPException(409, "用户名已被使用")

        code = req.invitation_code.strip()
        cursor = await db.execute(
            "SELECT id, used_by, expires_at FROM invitation_codes WHERE code = ?", (code,)
        )
        code_row = await cursor.fetchone()
        if not code_row:
            record_register_attempt(ip)
            await log_audit(None, "register_bad_code", request, f"code={code[:8]}")
            raise HTTPException(400, "邀请码无效")
        if code_row["used_by"]:
            record_register_attempt(ip)
            raise HTTPException(400, "邀请码已被使用")
        if code_row["expires_at"]:
            exp = datetime.fromisoformat(code_row["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                raise HTTPException(400, "邀请码已过期")

        nickname = req.nickname.strip() or username
        pw_hash = hash_password(req.password)
        cursor = await db.execute(
            "INSERT INTO users (username, password_hash, nickname, role, status) VALUES (?, ?, ?, 'user', 'active')",
            (username, pw_hash, nickname),
        )
        await db.commit()
        user_id = cursor.lastrowid

        await db.execute(
            "UPDATE invitation_codes SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id, code_row["id"]),
        )
        await db.commit()

        session_id = await create_session(user_id)
        is_https = request.headers.get("x-forwarded-proto") == "https"
        set_session_cookie(response, session_id, secure=is_https)

        await log_audit(user_id, "register", request)
        return {"success": True, "user": {"id": user_id, "username": username, "nickname": nickname}}
    finally:
        await db.close()


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    username = req.username.strip()
    check_login_rate_limit(ip, username)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, username, password_hash, nickname, role, status, can_invite FROM users WHERE username = ?",
            (username,),
        )
        user = await cursor.fetchone()
        if not user or not verify_password(req.password, user["password_hash"]):
            record_login_attempt(ip, username)
            await log_audit(None, "login_failed", request, f"username={username}")
            raise HTTPException(401, "用户名或密码错误")
        if user["status"] != "active":
            raise HTTPException(403, "账号已被禁用，请联系管理员")

        session_id = await create_session(user["id"])
        is_https = request.headers.get("x-forwarded-proto") == "https"
        set_session_cookie(response, session_id, secure=is_https)
        await log_audit(user["id"], "login", request)
        return {
            "success": True,
            "user": {
                "id": user["id"], "username": user["username"],
                "nickname": user["nickname"], "role": user["role"],
                "can_invite": bool(user["can_invite"]),
            },
        }
    finally:
        await db.close()


@router.post("/logout")
async def logout(response: Response, request: Request,
                 pw_session: str = None, current_user: dict = Depends(get_current_user)):
    if pw_session:
        await delete_session(pw_session)
    clear_session_cookie(response)
    await log_audit(current_user["id"], "logout", request)
    return {"success": True}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


# ── Password Management ────────────────────────────────

@router.put("/me/password")
async def change_password(req: ChangePasswordRequest, request: Request, response: Response,
                          current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        row = await (await db.execute("SELECT password_hash FROM users WHERE id = ?", (current_user["id"],))).fetchone()
        if not row or not verify_password(req.old_password, row["password_hash"]):
            raise HTTPException(400, "原密码错误")
        await db.execute("UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (hash_password(req.new_password), current_user["id"]))
        await db.commit()
        await delete_all_sessions(current_user["id"])
        clear_session_cookie(response)
        await log_audit(current_user["id"], "change_password", request)
        return {"success": True, "message": "密码已修改，请重新登录"}
    finally:
        await db.close()


@router.put("/me/profile")
async def update_profile(nickname: str = None, current_user: dict = Depends(get_current_user)):
    if not nickname or not nickname.strip():
        raise HTTPException(400, "昵称不能为空")
    db = await get_db()
    try:
        await db.execute("UPDATE users SET nickname = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (nickname.strip()[:50], current_user["id"]))
        await db.commit()
        return {"success": True, "nickname": nickname.strip()}
    finally:
        await db.close()


# ── Admin: Users ───────────────────────────────────────

@router.get("/admin/users")
async def list_users(admin: dict = Depends(require_admin), page: int = 1, page_size: int = 50):
    db = await get_db()
    try:
        total = (await (await db.execute("SELECT COUNT(*) as c FROM users")).fetchone())["c"]
        cursor = await db.execute(
            """SELECT id, username, nickname, role, status, can_invite, created_at, updated_at
               FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (page_size, (page - 1) * page_size),
        )
        return {"users": [dict(r) for r in await cursor.fetchall()], "total": total, "page": page}
    finally:
        await db.close()


@router.put("/admin/users/{user_id}")
async def update_user(user_id: int, req: AdminUpdateUserRequest,
                      request: Request, admin: dict = Depends(require_admin)):
    if admin["id"] == user_id and req.status == "disabled":
        raise HTTPException(400, "不能禁用自己的账号")

    db = await get_db()
    try:
        if not await (await db.execute("SELECT id FROM users WHERE id = ?", (user_id,))).fetchone():
            raise HTTPException(404, "用户不存在")

        updates, params = [], []
        if req.nickname is not None:
            updates.append("nickname = ?"); params.append(req.nickname)
        if req.role is not None and req.role in ("user", "admin"):
            updates.append("role = ?"); params.append(req.role)
        if req.status is not None and req.status in ("active", "disabled"):
            updates.append("status = ?"); params.append(req.status)
            if req.status == "disabled":
                await delete_all_sessions(user_id)
        if req.can_invite is not None:
            updates.append("can_invite = ?"); params.append(1 if req.can_invite else 0)
        if req.new_password:
            updates.append("password_hash = ?"); params.append(hash_password(req.new_password))
            await delete_all_sessions(user_id)

        if not updates:
            raise HTTPException(400, "没有要修改的字段")
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(user_id)
        await db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        await db.commit()
        await log_audit(admin["id"], "admin_update_user", request, f"target={user_id}")
        return {"success": True}
    finally:
        await db.close()


# ── Invitation Codes ───────────────────────────────────

@router.post("/invitations")
async def create_invitations(req: CreateInvitationRequest, request: Request,
                             user: dict = Depends(require_can_invite)):
    """Create invitation codes — admin or users with can_invite permission."""
    count = max(1, min(req.count, 20))
    expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_days)

    db = await get_db()
    try:
        codes = []
        for _ in range(count):
            code = f"PW-{secrets.token_hex(4).upper()}"
            await db.execute(
                "INSERT INTO invitation_codes (code, created_by, expires_at) VALUES (?, ?, ?)",
                (code, user["id"], expires_at.isoformat()),
            )
            codes.append(code)
        await db.commit()
        await log_audit(user["id"], "create_invitations", request, f"count={count}")
        return {"codes": codes, "expires_at": expires_at.isoformat()}
    finally:
        await db.close()


@router.get("/invitations")
async def list_invitations(user: dict = Depends(require_can_invite)):
    """List invitation codes — admin or users with can_invite."""
    db = await get_db()
    try:
        # Admin sees all; can_invite users see only their own
        if user["role"] == "admin":
            cursor = await db.execute(
                """SELECT ic.id, ic.code, ic.used_by, ic.used_at, ic.expires_at, ic.created_at,
                          u.username as used_by_username, c.username as created_by_username
                   FROM invitation_codes ic
                   LEFT JOIN users u ON ic.used_by = u.id
                   LEFT JOIN users c ON ic.created_by = c.id
                   ORDER BY ic.created_at DESC"""
            )
        else:
            cursor = await db.execute(
                """SELECT ic.id, ic.code, ic.used_by, ic.used_at, ic.expires_at, ic.created_at,
                          u.username as used_by_username, c.username as created_by_username
                   FROM invitation_codes ic
                   LEFT JOIN users u ON ic.used_by = u.id
                   LEFT JOIN users c ON ic.created_by = c.id
                   WHERE ic.created_by = ?
                   ORDER BY ic.created_at DESC""",
                (user["id"],),
            )
        return {"codes": [dict(r) for r in await cursor.fetchall()]}
    finally:
        await db.close()


@router.delete("/invitations/{code_id}")
async def delete_invitation(code_id: int, user: dict = Depends(require_can_invite)):
    db = await get_db()
    try:
        row = await (await db.execute("SELECT id, used_by, created_by FROM invitation_codes WHERE id = ?", (code_id,))).fetchone()
        if not row:
            raise HTTPException(404, "邀请码不存在")
        if row["used_by"]:
            raise HTTPException(400, "不能删除已使用的邀请码")
        # Non-admin can only delete their own codes
        if user["role"] != "admin" and row["created_by"] != user["id"]:
            raise HTTPException(403, "只能删除自己创建的邀请码")
        await db.execute("DELETE FROM invitation_codes WHERE id = ?", (code_id,))
        await db.commit()
        return {"success": True}
    finally:
        await db.close()


# ── User Config (LLM/Embedding/Theme) ──────────────────

@router.get("/me/config")
async def get_config(current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT user_config FROM users WHERE id = ?", (current_user["id"],)
        )).fetchone()
        import json
        cfg = json.loads(row["user_config"]) if row and row["user_config"] else {}
        # Never expose api_key values back — mask them
        if cfg.get("llm_api_key"):
            cfg["llm_api_key"] = "***" + cfg["llm_api_key"][-4:]
        if cfg.get("embed_api_key"):
            cfg["embed_api_key"] = "***" + cfg["embed_api_key"][-4:]
        return cfg
    finally:
        await db.close()


@router.put("/me/config")
async def update_config(config: dict, current_user: dict = Depends(get_current_user)):
    """Update user config. Masks api_key — only updates fields explicitly provided."""
    import json
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT user_config FROM users WHERE id = ?", (current_user["id"],)
        )).fetchone()
        existing = json.loads(row["user_config"]) if row and row["user_config"] else {}

        # Merge: only update keys that are provided
        for key in ("theme", "llm_base_url", "llm_api_key", "llm_model",
                     "embed_base_url", "embed_api_key", "embed_model"):
            if key in config:
                existing[key] = config[key]

        await db.execute(
            "UPDATE users SET user_config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(existing), current_user["id"]),
        )
        await db.commit()
        return {"success": True}
    finally:
        await db.close()


# ── Proxy: List models from user's LLM/Embedding API ───

@router.post("/proxy/models")
async def proxy_list_models(body: dict, current_user: dict = Depends(get_current_user)):
    """Proxy request to list models from a user-provided LLM/Embedding API.
    body: { provider: "llm"|"embed", base_url: str, api_key: str }
    Returns list of model IDs.
    """
    import httpx

    base_url = (body.get("base_url") or "").strip().rstrip("/")
    api_key = (body.get("api_key") or "").strip()

    if not base_url:
        raise HTTPException(400, "请填写 Base URL")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "Base URL 必须以 http:// 或 https:// 开头")
    if _is_ssrf_blocked(base_url):
        raise HTTPException(400, "不允许访问该地址")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            if resp.status_code == 404:
                resp = await client.get(f"{base_url}/v1/models", headers=headers)
            if resp.status_code != 200:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text[:200]
                raise HTTPException(502, f"API 返回错误 ({resp.status_code}): {detail}")

            data = resp.json()
            # Handle different response formats
            models = []
            if isinstance(data, list):
                models = data
            elif isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list):
                    models = data["data"]
                elif "models" in data:
                    models = data["models"]

            # Extract model IDs
            result = []
            for m in models:
                if isinstance(m, str):
                    result.append(m)
                elif isinstance(m, dict):
                    result.append(m.get("id") or m.get("name") or str(m))

            return {"models": result[:100]}

    except httpx.ConnectError:
        raise HTTPException(502, "无法连接到 API 服务器")
    except httpx.TimeoutException:
        raise HTTPException(502, "API 请求超时")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"请求失败: {str(e)}")


# ── Admin: Grant/Revoke invite permission ──────────────

@router.put("/admin/users/{user_id}/invite-permission")
async def set_invite_permission(user_id: int, can_invite: bool = True,
                                request: Request = None, admin: dict = Depends(require_admin)):
    """Admin grants or revokes invitation code generation permission."""
    db = await get_db()
    try:
        row = await (await db.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))).fetchone()
        if not row:
            raise HTTPException(404, "用户不存在")
        await db.execute("UPDATE users SET can_invite = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (1 if can_invite else 0, user_id))
        await db.commit()
        await log_audit(admin["id"], "set_invite_permission", request,
                        f"target={row['username']} can_invite={can_invite}")
        return {"success": True, "username": row["username"], "can_invite": can_invite}
    finally:
        await db.close()
