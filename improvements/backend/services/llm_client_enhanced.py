"""Enhanced LLM client with input sanitization."""

import json
import logging
from typing import Optional

import httpx
from backend.config import CONFIG
from backend.utils.sanitizer import sanitize_chat_query, create_safe_llm_prompt

logger = logging.getLogger(__name__)

LLM_CONFIG = CONFIG.get("llm", {})
API_BASE = LLM_CONFIG.get("api_base", "https://api.openai.com/v1")
API_KEY = LLM_CONFIG.get("api_key", "")
MODEL = LLM_CONFIG.get("model", "gpt-4o")
MAX_TOKENS = LLM_CONFIG.get("max_tokens", 8192)
TEMPERATURE = LLM_CONFIG.get("temperature", 0.3)
TIMEOUT = 120


async def llm_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    sanitize_input: bool = True,  # New parameter
) -> str:
    """
    Send a chat completion request to the LLM.

    Returns the assistant's response text.

    Args:
        sanitize_input: If True, sanitizes user_prompt to prevent injection
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    # Sanitize user input if requested
    if sanitize_input:
        user_prompt = sanitize_chat_query(user_prompt)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens or MAX_TOKENS,
        "temperature": temperature if temperature is not None else TEMPERATURE,
    }

    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{API_BASE}/chat/completions",
                headers=headers,
                json=payload,
            )

            if resp.status_code != 200:
                try:
                    err_text = resp.text
                except Exception:
                    err_text = resp.content.decode('utf-8', errors='replace')
                logger.error(f"LLM API error {resp.status_code}: {err_text[:500]}")
                raise RuntimeError(f"LLM API error {resp.status_code}")

            # Handle gzip-compressed responses
            try:
                data = resp.json()
            except UnicodeDecodeError:
                import gzip, io
                raw = gzip.decompress(resp.content)
                data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            logger.info(
                f"LLM response: {len(content)} chars, "
                f"tokens: {data.get('usage', {}).get('total_tokens', '?')}"
            )
            return content

    except httpx.TimeoutException:
        raise RuntimeError("LLM API timeout")
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot connect to LLM API at {API_BASE}")


async def llm_chat_safe(
    system_prompt: str,
    user_query: str,
    context: Optional[str] = None,
    **kwargs
) -> str:
    """
    Safe wrapper that uses delimited prompts to prevent injection.

    Recommended for user-facing chat interfaces.
    """
    safe_prompt = create_safe_llm_prompt(user_query, context)
    return await llm_chat(system_prompt, safe_prompt, sanitize_input=False, **kwargs)


async def llm_analyze(paper_markdown: str, wiki_context: str) -> dict:
    """
    Step 1 of two-step ingestion: Analyze the paper.

    Returns structured analysis JSON.

    Note: Paper markdown is trusted input (parsed PDF), so sanitization is disabled.
    """
    system_prompt = """你是一个学术论文分析专家。分析给定的论文，提取关键信息并识别与现有知识库的关联。

输出严格的 JSON 格式（不要包含 markdown 代码块标记），包含以下字段：
{
  "title": "论文标题",
  "authors": ["作者1", "作者2"],
  "year": 2024,
  "abstract": "论文摘要（中文，200字以内）",
  "key_entities": [
    {"name": "实体名", "type": "person|organization|model|dataset|framework", "description": "简要描述"}
  ],
  "key_concepts": [
    {"name": "概念名", "description": "简要描述", "importance": "high|medium|low"}
  ],
  "key_findings": ["发现1", "发现2"],
  "methodology": "方法概述（100字以内）",
  "connections": [
    {"target": "已有Wiki页面名", "relation": "关联描述", "strength": "strong|moderate|weak"}
  ],
  "contradictions": ["与已有知识的矛盾或张力"],
  "tags": ["标签1", "标签2"],
  "search_queries": ["用于深度研究的搜索查询"]
}"""

    user_prompt = f"""## 当前知识库上下文

{wiki_context}

## 论文内容

{paper_markdown[:30000]}

请分析这篇论文并输出 JSON。"""

    response = await llm_chat(system_prompt, user_prompt, json_mode=True, sanitize_input=False)

    # Parse JSON, handling potential markdown code blocks
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse LLM analysis JSON: {text[:200]}")
        # Try to fix common issues
        return {
            "title": "Unknown",
            "abstract": text[:500],
            "key_entities": [],
            "key_concepts": [],
            "key_findings": [],
            "tags": [],
        }


async def llm_generate(analysis: dict, wiki_structure: str) -> dict:
    """
    Step 2 of two-step ingestion: Generate wiki pages.

    Returns dict with keys: source_page, entity_pages, concept_pages, index_update, log_entry
    """
    system_prompt = """你是一个知识库编辑专家。基于论文分析结果，生成结构化的 Wiki 页面内容。

输出严格的 JSON 格式，包含以下字段：
{
  "source_page": {
    "filename": "paper-slug.md",
    "content": "完整的 Markdown 内容（含 YAML frontmatter）"
  },
  "entity_pages": [
    {
      "filename": "entity-name.md",
      "action": "create|update",
      "content": "完整的 Markdown 内容"
    }
  ],
  "concept_pages": [
    {
      "filename": "concept-name.md",
      "action": "create|update",
      "content": "完整的 Markdown 内容"
    }
  ],
  "index_additions": "要添加到 index.md 的新内容（Markdown 格式）",
  "log_entry": "操作日志条目（一行文本）",
  "overview_update": "全局概要的更新内容（Markdown 格式）"
}

YAML frontmatter 格式：
---
type: source|entity|concept
title: "标题"
sources: ["paper-id"]
tags: [tag1, tag2]
created: YYYY-MM-DD
---

使用 [[wikilink]] 格式引用其他 Wiki 页面。"""

    user_prompt = f"""## 论文分析结果

```json
{json.dumps(analysis, ensure_ascii=False, indent=2)}
```

## 当前 Wiki 结构

{wiki_structure}

请基于分析结果生成 Wiki 页面。今天是 {__import__('datetime').date.today().isoformat()}。"""

    response = await llm_chat(system_prompt, user_prompt, json_mode=True, sanitize_input=False)

    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse LLM generation JSON: {text[:200]}")
        return {
            "source_page": {"filename": "unknown.md", "content": f"# Unknown\n\n{analysis.get('abstract', '')}"},
            "entity_pages": [],
            "concept_pages": [],
            "index_addition": "",
            "log_entry": f"Failed to generate wiki pages",
        }
