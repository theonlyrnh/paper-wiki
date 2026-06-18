"""Embedding service — generates vector embeddings via GLM-Embedding-3 API."""

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
from backend.config import CONFIG

logger = logging.getLogger(__name__)

EMB_CONFIG = CONFIG.get("embedding", {})
API_BASE = EMB_CONFIG.get("api_base", "")
API_KEY = EMB_CONFIG.get("api_key", "")
MODEL = EMB_CONFIG.get("model", "GLM-Embedding-3")
DIMENSIONS = EMB_CONFIG.get("dimensions", 2048)
TIMEOUT = 30


def _valid_api_key() -> bool:
    return bool(API_KEY) and not API_KEY.startswith("your-") and not API_KEY.startswith("${")


def _valid_api_base() -> bool:
    if not API_BASE or API_BASE.startswith("${"):
        return False
    parsed = urlparse(API_BASE)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def config_status() -> dict:
    """Return sanitized embedding configuration status for API/UI checks."""
    if not _valid_api_key():
        return {
            "configured": False,
            "error": "EMBEDDING_API_KEY not configured",
            "model": MODEL,
            "dimensions": DIMENSIONS,
        }
    if not _valid_api_base():
        return {
            "configured": False,
            "error": "EMBEDDING_API_BASE must start with http:// or https://",
            "model": MODEL,
            "dimensions": DIMENSIONS,
        }
    return {
        "configured": True,
        "error": None,
        "model": MODEL,
        "dimensions": DIMENSIONS,
    }


def is_configured() -> bool:
    """Check if embedding API is configured with a valid key and endpoint."""
    return config_status()["configured"]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a batch of texts.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors, each a list of floats.

    Raises:
        RuntimeError: If API call fails.
    """
    if not texts:
        return []

    status = config_status()
    if not status["configured"]:
        raise RuntimeError(status["error"] or "Embedding API not configured")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    payload = {
        "model": MODEL,
        "input": texts,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{API_BASE}/embeddings",
                headers=headers,
                json=payload,
            )

            if resp.status_code != 200:
                try:
                    err = resp.text
                except Exception:
                    err = resp.content.decode("utf-8", errors="replace")
                logger.error(f"Embedding API error {resp.status_code}: {err[:300]}")
                raise RuntimeError(f"Embedding API error {resp.status_code}")

            # Handle gzip-compressed responses
            try:
                data = resp.json()
            except UnicodeDecodeError:
                import gzip
                raw = gzip.decompress(resp.content)
                import json
                data = json.loads(raw)

            embeddings = [item["embedding"] for item in data["data"]]
            logger.info(
                f"Generated {len(embeddings)} embeddings "
                f"({DIMENSIONS}d, model={MODEL})"
            )
            return embeddings

    except httpx.TimeoutException:
        raise RuntimeError("Embedding API timeout")
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to Embedding API endpoint")


async def embed_query(query: str) -> list[float]:
    """Generate embedding for a single query string."""
    results = await embed_texts([query])
    return results[0]


async def test_connection() -> dict:
    """Test the embedding API connection. Returns status info."""
    status = config_status()
    if not status["configured"]:
        return {"status": "not_configured", "error": status["error"]}

    try:
        embeddings = await embed_texts(["test connection"])
        if embeddings and len(embeddings[0]) > 0:
            return {
                "status": "ok",
                "model": MODEL,
                "dimensions": len(embeddings[0]),
            }
        return {"status": "error", "error": "Empty embedding returned"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
