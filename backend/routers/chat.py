"""Chat API — multi-turn conversation with knowledge base references + user isolation."""

import uuid
import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from backend.database import get_db
from backend.services.search_service import get_hybrid_search
from backend.services.llm_client import llm_chat
from backend.config import CONFIG
from backend.auth import get_current_user

# Rate limiting storage (in-memory)
_chat_rate_limits: dict[str, list[float]] = {}

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

WIKI_DIR = Path(__file__).parent.parent.parent / CONFIG["storage"]["wiki_dir"]
_hybrid_search = get_hybrid_search()


class ChatMessage(BaseModel):
    content: str
    session_id: Optional[str] = None


class SessionCreate(BaseModel):
    title: str = "新对话"


@router.post("/sessions")
async def create_session(
    body: SessionCreate,
    current_user: dict = Depends(get_current_user),
):
    session_id = str(uuid.uuid4())
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO chat_sessions (id, user_id, title) VALUES (?, ?, ?)",
            (session_id, current_user["id"], body.title),
        )
        await db.commit()
        return {"id": session_id, "title": body.title}
    finally:
        await db.close()


@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM chat_sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (current_user["id"],),
        )
        return [
            {"id": r["id"], "title": r["title"],
             "created_at": str(r["created_at"]), "updated_at": str(r["updated_at"])}
            for r in await cursor.fetchall()
        ]
    finally:
        await db.close()


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, current_user["id"]),
        )
        if not await cursor.fetchone():
            raise HTTPException(404, "Session not found")

        await db.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
                         (session_id, current_user["id"]))
        await db.commit()
        return {"message": "Session deleted"}
    finally:
        await db.close()


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = await get_db()
    try:
        # Verify ownership
        cursor = await db.execute(
            "SELECT id FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, current_user["id"]),
        )
        if not await cursor.fetchone():
            raise HTTPException(404, "Session not found")

        cursor = await db.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        messages = []
        for r in await cursor.fetchall():
            refs = None
            if r["references"]:
                try:
                    refs = json.loads(r["references"])
                except Exception:
                    pass
            messages.append({
                "id": r["id"], "role": r["role"], "content": r["content"],
                "references": refs, "created_at": str(r["created_at"]),
            })
        return messages
    finally:
        await db.close()


def _check_chat_rate(uid: int):
    key = f"chat:{uid}"
    now = time.time()
    window = 60  # 1 minute
    max_reqs = 20
    _chat_rate_limits.setdefault(key, [])
    _chat_rate_limits[key] = [t for t in _chat_rate_limits[key] if now - t < window]
    if len(_chat_rate_limits[key]) >= max_reqs:
        raise HTTPException(429, "对话请求过于频繁，请稍后再试")
    _chat_rate_limits[key].append(now)


@router.post("")
async def chat(
    msg: ChatMessage,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    _check_chat_rate(current_user["id"])
    session_id = msg.session_id or str(uuid.uuid4())
    uid = current_user["id"]

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, uid)
        )
        if not await cursor.fetchone():
            await db.execute(
                "INSERT INTO chat_sessions (id, user_id, title) VALUES (?, ?, ?)",
                (session_id, uid, msg.content[:30]),
            )
            await db.commit()

        user_msg_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO chat_messages (id, session_id, role, content) VALUES (?, ?, 'user', ?)",
            (user_msg_id, session_id, msg.content),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        history = await cursor.fetchall()
    finally:
        await db.close()

    # Search for relevant wiki pages (pass user_id for data isolation + dedup)
    search_results = await _hybrid_search.search(msg.content, top_k=8, user_id=uid)

    TYPE_DIRS = {"source": "sources", "entity": "entities", "concept": "concepts"}
    context_parts = []
    references = []
    seen_names = set()
    _TYPE_SINGULAR = {"sources": "source", "entities": "entity", "concepts": "concept"}
    for i, r in enumerate(search_results, 1):
        try:
            # Normalize name and type
            name = r["name"].replace(".md", "")
            if name in seen_names:
                continue
            seen_names.add(name)
            page_type = _TYPE_SINGULAR.get(r["type"], r["type"])

            subdir = TYPE_DIRS.get(page_type, TYPE_DIRS.get(r["type"], ""))
            page_path = WIKI_DIR / str(uid) / (subdir or "") / f"{name}.md"
            if page_path.exists():
                content = page_path.read_text(encoding="utf-8")
                lines = content.split("\n")
                body_start = 0
                if lines and lines[0] == "---":
                    for j, line in enumerate(lines[1:], 1):
                        if line == "---":
                            body_start = j + 1
                            break
                body = "\n".join(lines[body_start:]).strip()
            else:
                body = r.get("snippet", "")
            context_parts.append(f"[{i}] {r['title']} ({page_type})\n{body[:1500]}")
            references.append({
                "index": i, "name": name, "title": r["title"],
                "type": page_type, "score": r["score"],
            })
        except Exception:
            continue

    context_str = "\n\n---\n\n".join(context_parts) if context_parts else "_未找到相关页面_"

    system_prompt = f"""你是论文知识库的 AI 助手。基于以下知识库内容回答用户问题。

规则：
1. 使用知识库中的信息回答问题
2. 在回答中使用 [1] [2] [3] 等编号引用来源
3. 如果知识库中没有相关信息，如实说明
4. 回答使用中文
5. 对公式使用 LaTeX 语法：行内用 $...$，独立公式用 $$...$$

## 知识库内容

{context_str}

## 知识库统计
- 搜索到 {len(search_results)} 个相关页面
"""

    messages_text = []
    for h in history[:-1]:
        messages_text.append(f"{'用户' if h['role'] == 'user' else '助手'}: {h['content']}")

    user_prompt = ""
    if messages_text:
        user_prompt = "对话历史:\n" + "\n".join(messages_text[-6:]) + "\n\n"
    user_prompt += f"用户当前问题: {msg.content}"

    try:
        response = await llm_chat(system_prompt, user_prompt)
    except Exception as e:
        response = f"抱歉，LLM 调用失败: {e}"

    db = await get_db()
    try:
        assistant_msg_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO chat_messages (id, session_id, role, content, "references")
               VALUES (?, ?, 'assistant', ?, ?)""",
            (assistant_msg_id, session_id, response, json.dumps(references)),
        )
        await db.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (session_id, uid),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "session_id": session_id,
        "message": {
            "id": assistant_msg_id, "role": "assistant",
            "content": response, "references": references,
        },
    }
