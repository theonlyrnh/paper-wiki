"""LLM client for Paper Wiki — supports OpenAI-compatible APIs."""

import asyncio
import json
import logging
import re
from typing import Optional

import httpx
from backend.config import CONFIG

logger = logging.getLogger(__name__)

LLM_CONFIG = CONFIG.get("llm", {})
API_BASE = LLM_CONFIG.get("api_base", "https://api.openai.com/v1")
API_KEY = LLM_CONFIG.get("api_key", "")
MODEL = LLM_CONFIG.get("model", "gpt-4o")
MAX_TOKENS = LLM_CONFIG.get("max_tokens", 8192)
TEMPERATURE = LLM_CONFIG.get("temperature", 0.3)
MAX_CONTEXT_TOKENS = LLM_CONFIG.get("max_context_tokens", 128000)

# Context budget allocation (chars, derived from max_context_tokens)
# ~2.5 chars per token for mixed Chinese/English
_CHARS_PER_TOKEN = 2.5
MAX_PAPER_CHARS = int(MAX_CONTEXT_TOKENS * 0.75 * _CHARS_PER_TOKEN)   # 75% of context for paper
MAX_WIKI_CHARS = int(MAX_CONTEXT_TOKENS * 0.10 * _CHARS_PER_TOKEN)    # 10% of context for wiki
MAX_USER_INPUT = 8000  # Max characters for chat user messages
TIMEOUT_CONFIG = LLM_CONFIG.get("timeout", {}) if isinstance(LLM_CONFIG.get("timeout", {}), dict) else {}
RETRY_CONFIG = LLM_CONFIG.get("retry", {}) if isinstance(LLM_CONFIG.get("retry", {}), dict) else {}
INGEST_CONFIG = CONFIG.get("ingest", {}) if isinstance(CONFIG.get("ingest", {}), dict) else {}

DEFAULT_TIMEOUT = 120
DEFAULT_ANALYZE_TIMEOUT = 360
DEFAULT_GENERATE_TIMEOUT = 300
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_WRITE_TIMEOUT = 60
DEFAULT_POOL_TIMEOUT = 30
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = [5, 15, 45]

LLM_MAX_CONCURRENCY = max(1, int(INGEST_CONFIG.get("llm_max_concurrency", 1) or 1))
_llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)


class LLMError(RuntimeError):
    """Base LLM error with a machine-readable type for ingestion diagnostics."""

    def __init__(self, message: str, *, error_type: str = "llm_error"):
        super().__init__(message)
        self.error_type = error_type


class LLMJSONParseError(LLMError):
    """Raised when an LLM response cannot be parsed as valid JSON."""

    def __init__(self, stage: str, sample: str):
        super().__init__(
            f"Failed to parse LLM {stage} JSON",
            error_type="llm_json_parse_failed",
        )
        self.stage = stage
        self.sample = sample[:500]


def is_retryable_llm_status(status_code: int) -> bool:
    """Return whether an HTTP status should be retried for LLM calls."""
    return status_code in {408, 409, 429, 500, 502, 503, 504}


def _int_config(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_list_config(value, default: list[float]) -> list[float]:
    if not isinstance(value, list) or not value:
        return default
    out = []
    for item in value:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out or default


def _timeout_for_stage(stage: str) -> httpx.Timeout:
    """Build an httpx timeout object from config with stage-specific read timeout."""
    if stage == "analyze":
        read_default = DEFAULT_ANALYZE_TIMEOUT
        read_key = "read_analyze"
    elif stage == "generate":
        read_default = DEFAULT_GENERATE_TIMEOUT
        read_key = "read_generate"
    else:
        read_default = DEFAULT_TIMEOUT
        read_key = "read"

    return httpx.Timeout(
        connect=_int_config(TIMEOUT_CONFIG.get("connect"), DEFAULT_CONNECT_TIMEOUT),
        read=_int_config(TIMEOUT_CONFIG.get(read_key, TIMEOUT_CONFIG.get("read")), read_default),
        write=_int_config(TIMEOUT_CONFIG.get("write"), DEFAULT_WRITE_TIMEOUT),
        pool=_int_config(TIMEOUT_CONFIG.get("pool"), DEFAULT_POOL_TIMEOUT),
    )


def _max_attempts() -> int:
    return max(1, _int_config(RETRY_CONFIG.get("max_attempts"), DEFAULT_MAX_ATTEMPTS))


def _backoff_seconds() -> list[float]:
    return _float_list_config(RETRY_CONFIG.get("backoff_seconds"), DEFAULT_BACKOFF_SECONDS)


def _strip_markdown_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    return text


def parse_llm_json_response(response: str, *, stage: str) -> dict:
    """Parse LLM JSON responses without silently falling back to Unknown pages."""
    text = _strip_markdown_json_fence(response)
    candidates = [text]

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        extracted = text[first:last + 1].strip()
        if extracted != text:
            candidates.append(extracted)

    last_error = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError("top-level JSON must be an object", candidate, 0)
            return parsed
        except json.JSONDecodeError as exc:
            last_error = exc

    logger.error(
        "Failed to parse LLM %s JSON: %s",
        stage,
        text[:200].replace("\n", "\\n"),
    )
    raise LLMJSONParseError(stage, text) from last_error


def sanitize_user_input(text: str, max_len: int = MAX_USER_INPUT) -> str:
    """Sanitize user input to prevent prompt injection and abuse."""
    if not text:
        return ""
    # Remove control characters (except newlines and tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    # Limit length
    if len(text) > max_len:
        text = text[:max_len] + "\n... [truncated]"
    return text


async def llm_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    stage: str = "default",
) -> str:
    """
    Send a chat completion request to the LLM.

    Returns the assistant's response text.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

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

    attempts = _max_attempts()
    backoff = _backoff_seconds()
    async with _llm_semaphore:
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=_timeout_for_stage(stage)) as client:
                    resp = await client.post(
                        f"{API_BASE}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                    if resp.status_code != 200:
                        try:
                            err_text = resp.text
                        except Exception:
                            err_text = resp.content.decode("utf-8", errors="replace")
                        logger.error(f"LLM API error {resp.status_code}: {err_text[:500]}")
                        if is_retryable_llm_status(resp.status_code) and attempt < attempts:
                            await asyncio.sleep(backoff[min(attempt - 1, len(backoff) - 1)])
                            continue
                        error_type = "llm_retryable_http_error" if is_retryable_llm_status(resp.status_code) else "llm_http_error"
                        raise LLMError(f"LLM API error {resp.status_code}", error_type=error_type)

                    # Handle gzip-compressed responses
                    try:
                        data = resp.json()
                    except UnicodeDecodeError:
                        import gzip
                        raw = gzip.decompress(resp.content)
                        data = json.loads(raw)
                    content = data["choices"][0]["message"].get("content") or ""
                    usage = data.get('usage', {})
                    logger.info(
                        f"LLM response: {len(content)} chars, "
                        f"tokens: {usage.get('total_tokens', '?')}, "
                        f"attempt: {attempt}/{attempts}, stage: {stage}"
                    )
                    # Empty content with tokens consumed means model spent budget on
                    # reasoning/thinking without producing output — retryable
                    if not content and usage.get('total_tokens', 0) > 0:
                        if attempt < attempts:
                            wait = backoff[min(attempt - 1, len(backoff) - 1)]
                            logger.warning(
                                f"LLM returned empty content (tokens={usage.get('total_tokens')}) "
                                f"— retrying in {wait}s"
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise LLMError(
                            "LLM returned empty content after all retries",
                            error_type="llm_empty_response",
                        )
                    return content

            except httpx.TimeoutException as exc:
                if attempt < attempts:
                    await asyncio.sleep(backoff[min(attempt - 1, len(backoff) - 1)])
                    continue
                raise LLMError("LLM API timeout", error_type="llm_timeout") from exc
            except httpx.ConnectError as exc:
                if attempt < attempts:
                    await asyncio.sleep(backoff[min(attempt - 1, len(backoff) - 1)])
                    continue
                raise LLMError("Cannot connect to LLM API endpoint", error_type="llm_connect_error") from exc

    raise LLMError("LLM API request failed", error_type="llm_error")


async def llm_analyze(paper_markdown: str, wiki_context: str) -> dict:
    """
    Step 1 of two-step ingestion: Analyze the paper.

    Returns structured analysis JSON.
    """
    system_prompt = """你是一个学术论文分析专家。分析给定的论文，提取关键信息并识别与现有知识库的关联。

语言要求：所有 title、name、description、abstract、findings、methodology 等文本内容必须使用中文。

输出严格的 JSON 格式（不要包含 markdown 代码块标记），包含以下字段：
{
  "title": "论文标题（中文翻译）",
  "authors": ["作者1", "作者2"],
  "year": 2024,
  "abstract": "论文摘要（中文，200字以内）",
  "key_entities": [
    {"name": "实体名（中文）", "type": "person|organization|model|dataset|framework", "description": "简要描述（中文）"}
  ],
  "key_concepts": [
    {"name": "概念名（中文）", "description": "简要描述（中文）", "importance": "high|medium|low"}
  ],
  "key_findings": ["发现1（中文）", "发现2（中文）"],
  "methodology": "方法概述（中文，100字以内）",
  "connections": [
    {"target": "已有Wiki页面名", "relation": "关联描述（中文）", "strength": "strong|moderate|weak"}
  ],
  "contradictions": ["与已有知识的矛盾或张力"],
  "tags": ["标签1（中文）", "标签2（中文）"],
  "search_queries": ["用于深度研究的搜索查询"]
}"""

    user_prompt = f"""## 当前知识库上下文

{sanitize_user_input(wiki_context, max_len=MAX_WIKI_CHARS)}

## 论文内容

{sanitize_user_input(paper_markdown, max_len=MAX_PAPER_CHARS)}

请分析这篇论文并输出 JSON。"""

    response = await llm_chat(system_prompt, user_prompt, json_mode=True, stage="analyze")
    return parse_llm_json_response(response, stage="analysis")


async def llm_generate(analysis: dict, wiki_structure: str) -> dict:
    """
    Step 2 of two-step ingestion: Generate wiki pages.

    Returns dict with keys: source_page, entity_pages, concept_pages, index_update, log_entry
    """
    system_prompt = """你是一个知识库编辑专家。基于论文分析结果，生成结构化的 Wiki 页面内容。

语言要求：Wiki 页面的标题、正文内容全部使用中文。文件名使用中文拼音或英文 slug。

输出严格的 JSON 格式，包含以下字段：
{
  "source_page": {
    "filename": "paper-slug.md",
    "content": "完整的 Markdown 内容（含 YAML frontmatter，标题和内容用中文）"
  },
  "entity_pages": [
    {
      "filename": "entity-slug.md",
      "action": "create|update",
      "content": "完整的 Markdown 内容（中文）"
    }
  ],
  "concept_pages": [
    {
      "filename": "concept-slug.md",
      "action": "create|update",
      "content": "完整的 Markdown 内容（中文）"
    }
  ],
  "index_additions": "要添加到 index.md 的新内容（Markdown 格式，中文）",
  "log_entry": "操作日志条目（一行中文文本）",
  "overview_update": "全局概要的更新内容（Markdown 格式，中文）"
}

文件名命名规则：
- 使用英文小写字母、数字和连字符，以 .md 结尾
- 禁止使用 "unknown"、"untitled"、"无标题" 作为文件名
- 从论文标题或概念名称生成有意义的 slug，例如：
  - "Attention Is All You Need" → attention-is-all-you-need.md
  - "多头注意力机制" → multi-head-attention.md
  - "Transformer架构" → transformer-architecture.md

YAML frontmatter 格式：
---
type: source|entity|concept
title: "中文标题"
sources: ["paper-id"]
tags: [标签1, 标签2]
created: YYYY-MM-DD
---

使用 [[wikilink]] 格式引用其他 Wiki 页面。wikilink 中的显示文本使用中文。"""

    user_prompt = f"""## 论文分析结果

```json
{json.dumps(analysis, ensure_ascii=False, indent=2)}
```

## 当前 Wiki 结构

{wiki_structure}

请基于分析结果生成 Wiki 页面。今天是 {__import__('datetime').date.today().isoformat()}。"""

    response = await llm_chat(system_prompt, user_prompt, json_mode=True, stage="generate")
    return parse_llm_json_response(response, stage="generation")
