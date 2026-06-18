"""Persistent cache for PDF evidence image slices.

The cache is intentionally keyed by the markdown snippets when snippets are
available. Search queries may vary, but the source-highlight snippets for a
Wiki page are deterministic; using snippets as the key lets cached evidence
survive raw PDF deletion and still be reused from search/chat source panels.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import CONFIG, PROJECT_ROOT

EVIDENCE_ALGORITHM_VERSION = "pdf-highlight-cache-v1"


def default_cache_root() -> Path:
    relative = CONFIG.get("storage", {}).get("evidence_dir", "data/evidence")
    path = PROJECT_ROOT / relative
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paper_cache_dir(cache_root: Path, user_id: int, paper_id: str) -> Path:
    return cache_root / str(user_id) / paper_id


def _manifest_path(cache_root: Path, user_id: int, paper_id: str) -> Path:
    return _paper_cache_dir(cache_root, user_id, paper_id) / "manifest.json"


def _read_manifest(cache_root: Path, user_id: int, paper_id: str) -> dict[str, Any]:
    path = _manifest_path(cache_root, user_id, paper_id)
    if not path.exists():
        return {"version": EVIDENCE_ALGORITHM_VERSION, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": EVIDENCE_ALGORITHM_VERSION, "entries": {}}
    if not isinstance(data, dict):
        return {"version": EVIDENCE_ALGORITHM_VERSION, "entries": {}}
    data.setdefault("version", EVIDENCE_ALGORITHM_VERSION)
    data.setdefault("entries", {})
    return data


def _write_manifest(cache_root: Path, user_id: int, paper_id: str, manifest: dict[str, Any]) -> None:
    path = _manifest_path(cache_root, user_id, paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _normalize_snippets(snippets: list[dict] | None) -> list[dict[str, Any]]:
    normalized = []
    for item in (snippets or [])[:8]:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        normalized.append({
            "text": " ".join(text.split())[:1200],
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
        })
    return normalized


def build_highlight_cache_key(query: str = "", snippets: list[dict] | None = None) -> str:
    normalized_snippets = _normalize_snippets(snippets)
    if normalized_snippets:
        payload = {"version": EVIDENCE_ALGORITHM_VERSION, "snippets": normalized_snippets}
    else:
        payload = {
            "version": EVIDENCE_ALGORITHM_VERSION,
            "query": " ".join(str(query or "").lower().split())[:1200],
        }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    if "," not in data_url:
        return "image/jpeg", base64.b64decode(data_url)
    header, payload = data_url.split(",", 1)
    mime = "image/jpeg"
    if header.startswith("data:") and ";" in header:
        mime = header[5:].split(";", 1)[0] or mime
    return mime, base64.b64decode(payload)


def _encode_image_file(path: Path, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def cache_slices(
    *,
    cache_root: Path | None = None,
    user_id: int,
    paper_id: str,
    paper_title: str,
    filename: str,
    cache_key: str,
    slices: list[dict],
) -> dict[str, Any]:
    cache_root = cache_root or default_cache_root()
    paper_dir = _paper_cache_dir(cache_root, user_id, paper_id)
    image_dir = paper_dir / "slices"
    image_dir.mkdir(parents=True, exist_ok=True)

    stored_slices = []
    response_slices = []
    for index, item in enumerate(slices or []):
        image_value = item.get("image", "")
        if not image_value:
            continue
        mime, image_bytes = _decode_data_url(image_value)
        ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
        image_name = f"{cache_key}-{index}{ext}"
        image_path = image_dir / image_name
        image_path.write_bytes(image_bytes)
        rel_image = f"slices/{image_name}"
        stored = {
            "page": item.get("page"),
            "total_pages": item.get("total_pages"),
            "image_file": rel_image,
            "image_mime": mime,
            "text": item.get("text", ""),
            "score": item.get("score", 0),
        }
        stored_slices.append(stored)
        response_slices.append({
            "page": stored["page"],
            "total_pages": stored["total_pages"],
            "image": _encode_image_file(image_path, mime),
            "text": stored["text"],
            "score": stored["score"],
        })

    manifest = _read_manifest(cache_root, user_id, paper_id)
    manifest["version"] = EVIDENCE_ALGORITHM_VERSION
    manifest["updated_at"] = _now_iso()
    manifest.setdefault("entries", {})[cache_key] = {
        "paper_title": paper_title,
        "filename": filename,
        "cache_key": cache_key,
        "updated_at": _now_iso(),
        "slices": stored_slices,
    }
    _write_manifest(cache_root, user_id, paper_id, manifest)

    return {
        "cache_status": "stored",
        "cache_key": cache_key,
        "paper_title": paper_title,
        "slices": response_slices,
    }


def get_cached_slices(
    *,
    cache_root: Path | None = None,
    user_id: int,
    paper_id: str,
    cache_key: str,
) -> dict[str, Any] | None:
    cache_root = cache_root or default_cache_root()
    paper_dir = _paper_cache_dir(cache_root, user_id, paper_id)
    manifest = _read_manifest(cache_root, user_id, paper_id)
    entry = manifest.get("entries", {}).get(cache_key)
    if not entry:
        return None

    slices = []
    for item in entry.get("slices", []):
        image_file = item.get("image_file")
        if not image_file:
            continue
        image_path = paper_dir / image_file
        if not image_path.exists():
            continue
        mime = item.get("image_mime", "image/jpeg")
        slices.append({
            "page": item.get("page"),
            "total_pages": item.get("total_pages"),
            "image": _encode_image_file(image_path, mime),
            "text": item.get("text", ""),
            "score": item.get("score", 0),
        })

    if not slices:
        return None
    return {
        "cache_status": "hit",
        "cache_key": cache_key,
        "paper_title": entry.get("paper_title", ""),
        "slices": slices,
    }
