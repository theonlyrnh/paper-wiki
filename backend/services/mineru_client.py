"""MinerU API client for PDF parsing, with pypdf fallback."""

import os
import logging
from pathlib import Path

import httpx

from backend.config import CONFIG

logger = logging.getLogger(__name__)

MINERU_API_URL = CONFIG["mineru"]["api_url"]
MINERU_TIMEOUT = CONFIG["mineru"]["timeout"]


async def check_mineru_health() -> bool:
    """Check if the MinerU API service is running."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MINERU_API_URL}/health")
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"MinerU health check failed: {e}")
        return False


def _extract_text_pypdf(pdf_path: str) -> str:
    """Fallback: extract text from PDF using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages_text.append(f"<!-- Page {i + 1} -->\n\n{text}")
    return "\n\n".join(pages_text)


async def parse_pdf(pdf_path: str) -> dict:
    """
    Parse a PDF file. Tries MinerU API first, falls back to pypdf.

    Returns:
        dict with keys: success, error, markdown, images
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"success": False, "error": f"File not found: {pdf_path}", "markdown": "", "images": []}

    # Try MinerU API
    result = await _parse_via_mineru(str(pdf_path))
    if result["success"]:
        return result

    # Fallback to pypdf
    logger.warning(f"MinerU failed ({result['error']}), falling back to pypdf for {pdf_path.name}")
    try:
        text = _extract_text_pypdf(str(pdf_path))
        if text.strip():
            logger.info(f"pypdf extracted {len(text)} chars from {pdf_path.name}")
            return {
                "success": True,
                "error": "",
                "markdown": text,
                "images": [],
                "parser": "pypdf",
            }
        else:
            return {
                "success": False,
                "error": f"MinerU failed: {result['error']}. pypdf extracted no text.",
                "markdown": "",
                "images": [],
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"MinerU failed: {result['error']}. pypdf also failed: {e}",
            "markdown": "",
            "images": [],
        }


async def _parse_via_mineru(pdf_path: str) -> dict:
    """Try parsing via MinerU API."""
    pdf_path = Path(pdf_path)

    try:
        async with httpx.AsyncClient(timeout=MINERU_TIMEOUT) as client:
            with open(pdf_path, "rb") as f:
                # MinerU API expects 'files' as an array
                files = [("files", (pdf_path.name, f, "application/pdf"))]
                resp = await client.post(
                    f"{MINERU_API_URL}/file_parse",
                    files=files,
                )

            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"MinerU HTTP {resp.status_code}: {resp.text[:300]}",
                    "markdown": "",
                    "images": [],
                }

            data = resp.json()

            # Check task status
            status = data.get("status", "")
            if status == "failed":
                return {
                    "success": False,
                    "error": f"MinerU task failed: {data.get('error', 'unknown')}",
                    "markdown": "",
                    "images": [],
                }

            # Extract markdown — handle both old and new MinerU API response formats
            md_content = ""
            # New API v2: results -> filename -> md_content
            results = data.get("results", {})
            if isinstance(results, dict) and results:
                first_result = next(iter(results.values()), {})
                if isinstance(first_result, dict):
                    md_content = first_result.get("md_content", "")
                elif isinstance(first_result, str):
                    md_content = first_result
            # Old API: md_content at root level
            if not md_content:
                md_content = data.get("md_content", "")
            if isinstance(md_content, dict):
                md_content = next(iter(md_content.values()), "")
            elif isinstance(md_content, list):
                md_content = md_content[0] if md_content else ""

            if not md_content:
                # Try alternative keys
                md_content = data.get("markdown", "")

            images = data.get("images", [])
            if isinstance(images, dict):
                images = list(images.values())

            return {
                "success": True,
                "error": "",
                "markdown": md_content,
                "images": images,
                "parser": "mineru",
            }

    except httpx.TimeoutException:
        return {"success": False, "error": "MinerU API timeout", "markdown": "", "images": []}
    except httpx.ConnectError:
        return {"success": False, "error": "MinerU API unavailable", "markdown": "", "images": []}
    except Exception as e:
        logger.exception(f"MinerU parse error for {pdf_path.name}")
        return {"success": False, "error": str(e), "markdown": "", "images": []}
