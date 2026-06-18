"""PDF highlight slice generation helpers."""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path


def strip_markdown_for_highlight(text: str) -> str:
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", "", text)
    text = re.sub(r"\$\$(.+?)\$\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\$(.+?)\$", r"\1", text)
    text = re.sub(r"\|[-|]+\|", "", text)
    text = re.sub(r"\|\s*", " ", text)
    return text.strip()


def find_relevant_paragraphs(paper_md: str, search_text: str, top_n: int = 5) -> list[dict]:
    """Find markdown paragraphs most relevant to a search/wiki text."""
    paragraphs = []
    lines = paper_md.split("\n")
    current = []
    current_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "":
            if current:
                paragraphs.append({"text": "\n".join(current), "start": current_start, "end": i - 1})
                current = []
            continue
        if not current:
            current_start = i
        current.append(line)
    if current:
        paragraphs.append({"text": "\n".join(current), "start": current_start, "end": len(lines) - 1})

    query_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", search_text.lower()))
    if not query_terms:
        return []

    skip_patterns = [
        "provided proper attribution", "copyright", "all rights reserved",
        "acknowledgment", "acknowledgement", "references", "doi:", "arxiv:",
    ]
    scored = []
    for para in paragraphs:
        text_lower = para["text"].lower()
        if any(pattern in text_lower for pattern in skip_patterns):
            continue
        if len(para["text"]) < 50:
            continue
        score = sum(1 for term in query_terms if term in text_lower)
        if score > 0:
            scored.append({**para, "score": score, "max_terms": len(query_terms)})

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_n]


def generate_pdf_highlight_slices(
    *,
    pdf_path: Path,
    snippets: list[dict] | None = None,
    query: str = "",
    max_slices: int = 8,
    jpeg_quality: int = 75,
) -> list[dict]:
    """Generate base64 JPEG image slices around PDF blocks matching snippets/query."""
    import fitz  # PyMuPDF
    from PIL import Image

    snippets = snippets or []
    snippet_terms = set()
    for snippet in snippets[:4]:
        snippet_terms.update(re.findall(r"[\w\u4e00-\u9fff]{3,}", str(snippet.get("text", "")).lower()))
    query_terms = set(re.findall(r"[\w\u4e00-\u9fff]{3,}", str(query or "").lower()))
    all_terms = snippet_terms | query_terms
    if not all_terms:
        return []

    doc = fitz.open(str(pdf_path))
    try:
        page_blocks = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            blocks = page.get_text("blocks")
            for block in blocks:
                if len(block) < 4:
                    continue
                text = block[4].strip()
                if len(text) < 30:
                    continue
                lower_text = text.lower()
                matched = sum(1 for term in all_terms if term in lower_text)
                if matched > 0:
                    page_blocks.append({
                        "page": page_num,
                        "rect": fitz.Rect(block[0], block[1], block[2], block[3]),
                        "text": text[:300],
                        "matched": matched,
                    })

        page_blocks.sort(key=lambda x: (-x["matched"], x["page"]))
        seen_pages: dict[int, int] = {}
        best_blocks = []
        for block in page_blocks:
            page_id = block["page"]
            seen_pages.setdefault(page_id, 0)
            if seen_pages[page_id] < 2:
                best_blocks.append(block)
                seen_pages[page_id] += 1
            if len(best_blocks) >= max_slices:
                break

        max_matched = max((block["matched"] for block in best_blocks), default=1)
        max_matched = max(max_matched, 1)

        results = []
        mat = fitz.Matrix(1.5, 1.5)
        for block in best_blocks[:max_slices]:
            page = doc[block["page"]]
            rect = block["rect"]
            pad = 30
            clip_rect = fitz.Rect(
                max(0, rect.x0 - pad),
                max(0, rect.y0 - pad),
                min(page.rect.width, rect.x1 + pad),
                min(page.rect.height, rect.y1 + pad * 2),
            )
            pix = page.get_pixmap(matrix=mat, clip=clip_rect)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
            image_b64 = base64.b64encode(buf.getvalue()).decode()
            buf.close()
            score_pct = max(1, min(99, round((block["matched"] / max_matched) * 99)))
            results.append({
                "page": block["page"] + 1,
                "total_pages": len(doc),
                "image": f"data:image/jpeg;base64,{image_b64}",
                "text": block["text"][:200],
                "score": score_pct,
            })
        return results
    finally:
        doc.close()
