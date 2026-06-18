"""Full-text search engine with jieba tokenization and inverted index."""

import json
import logging
import math
import re
from pathlib import Path
from collections import defaultdict
from typing import Optional

import jieba
from backend.config import CONFIG

logger = logging.getLogger(__name__)

WIKI_BASE = Path(__file__).parent.parent.parent / CONFIG["storage"]["wiki_dir"]

# English stop words
STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
    'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
    'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'between', 'out', 'off', 'over', 'under', 'again', 'further', 'then',
    'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'both',
    'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
    'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
    'because', 'but', 'and', 'or', 'if', 'while', 'about', 'up', 'that',
    'this', 'these', 'those', 'which', 'what', 'who', 'whom', 'its', 'it',
    'he', 'she', 'they', 'them', 'his', 'her', 'their', 'my', 'your', 'we',
    'you', 'me', 'him', 'us', 'i',
}


def tokenize(text: str) -> list[str]:
    """Tokenize text using jieba for Chinese and simple split for English."""
    # Remove markdown formatting
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)  # links
    text = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', text)  # images
    text = re.sub(r'#{1,6}\s+', '', text)  # headings
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)  # italic
    text = re.sub(r'`([^`]+)`', r'\1', text)  # code
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL | re.MULTILINE)  # frontmatter
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)  # wikilinks -> plain text

    # Tokenize with jieba
    tokens = jieba.lcut(text)

    # Filter
    result = []
    for token in tokens:
        token = token.strip().lower()
        if len(token) < 2:
            continue
        if token in STOP_WORDS:
            continue
        if re.match(r'^[\d\s\.\-\/]+$', token):
            continue
        result.append(token)

    return result


def _contains_cjk(text: str) -> bool:
    """Return True when text contains CJK unified ideographs."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _allow_partial_match(token: str) -> bool:
    """Allow shorter partial matching for Chinese tokens than English tokens."""
    if _contains_cjk(token):
        return len(token) >= 2
    return len(token) >= 3


def _terms_match(query_token: str, index_token: str) -> bool:
    """Return whether a query token should match an indexed token."""
    if query_token == index_token:
        return True
    if not _allow_partial_match(query_token):
        return False
    return query_token in index_token or index_token in query_token


def _is_unknown_title(title: str | None) -> bool:
    if not title:
        return True
    return title.strip().lower() in {"unknown", "untitled", "无标题", "未知"}


class WikiSearchEngine:
    """In-memory inverted index for wiki pages."""

    def __init__(self):
        self.index = defaultdict(set)  # token -> set of page names
        self.documents = {}  # page_name -> {title, type, path, content}
        self.doc_lengths = {}  # page_name -> token count
        self.avg_dl = 1.0
        self._built = False
        self._user_id = None

    def build_index(self, user_id: int = None):
        """Build the inverted index from wiki markdown files (per-user)."""
        wiki_dir = WIKI_BASE / str(user_id) if user_id else WIKI_BASE
        self.build_index_from_dir(wiki_dir, user_id=user_id)

    def build_index_from_dir(self, wiki_dir: Path, user_id: int = None):
        """Build the inverted index from an explicit wiki directory."""
        self.index.clear()
        self.documents.clear()
        self.doc_lengths.clear()
        self._user_id = user_id

        for subdir in ["sources", "entities", "concepts", ""]:
            search_dir = wiki_dir / subdir if subdir else wiki_dir
            if not search_dir.exists():
                continue
            for md_file in search_dir.glob("*.md"):
                if md_file.name in ("index.md", "log.md", "overview.md"):
                    if subdir:
                        continue
                self._index_file(md_file, wiki_dir)

        for name in ("index.md", "overview.md"):
            path = wiki_dir / name
            if path.exists():
                self._index_file(path, wiki_dir)

        if self.doc_lengths:
            self.avg_dl = sum(self.doc_lengths.values()) / len(self.doc_lengths)
        else:
            self.avg_dl = 1.0
        self._built = True
        logger.info(f"Search index built: {len(self.documents)} docs, {len(self.index)} terms")

    def _index_file(self, path: Path, wiki_dir: Path = None):
        """Index a single markdown file."""
        if wiki_dir is None:
            wiki_dir = WIKI_BASE
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return

        _DIR_TO_TYPE = {"sources": "source", "entities": "entity", "concepts": "concept"}
        try:
            rel = path.relative_to(wiki_dir)
        except ValueError:
            rel = Path(path.name)
        parts = rel.parts
        page_type = _DIR_TO_TYPE.get(parts[0], "root") if len(parts) > 1 else "root"

        # Extract title
        title = path.stem.replace("-", " ").title()
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                candidate = line[2:].strip()
                if not _is_unknown_title(candidate):
                    title = candidate
                break

        page_name = path.stem
        self.documents[page_name] = {
            "name": page_name,
            "title": title,
            "type": page_type,
            "path": str(path),
        }

        tokens = tokenize(content)
        self.doc_lengths[page_name] = len(tokens)

        for token in set(tokens):
            self.index[token].add(page_name)

    def search(self, query: str, top_k: int = 20, user_id: int = None) -> list[dict]:
        """Search wiki pages. Returns ranked results using BM25."""
        if not self._built or getattr(self, '_user_id', None) != user_id:
            self.build_index(user_id)

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = defaultdict(float)
        N = len(self.documents) or 1
        k1 = 1.5
        b = 0.75

        for token in set(query_tokens):
            # Find matching documents
            matching_docs = set()

            for idx_token, docs in self.index.items():
                if _terms_match(token, idx_token):
                    matching_docs.update(docs)

            if not matching_docs:
                continue

            # IDF
            df = len(matching_docs)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)

            for doc_name in matching_docs:
                doc = self.documents.get(doc_name)
                if not doc:
                    continue

                # TF (simplified — count token occurrences)
                content = ""
                try:
                    content = Path(doc["path"]).read_text(encoding="utf-8")
                except Exception:
                    continue
                doc_tokens = tokenize(content)
                tf = sum(1 for doc_token in doc_tokens if _terms_match(token, doc_token))
                if tf <= 0:
                    continue

                dl = self.doc_lengths.get(doc_name, 1)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self.avg_dl))

                score = idf * tf_norm

                # Title boost
                title_tokens = tokenize(doc["title"])
                if any(_terms_match(token, title_token) for title_token in title_tokens):
                    score *= 3.0

                if score > 0:
                    scores[doc_name] += score

        # Sort by score
        ranked = sorted(
            ((name, score) for name, score in scores.items() if score > 0),
            key=lambda x: -x[1],
        )[:top_k]

        results = []
        for name, score in ranked:
            doc = self.documents.get(name, {})
            # Read first 200 chars as snippet
            snippet = ""
            try:
                content = Path(doc["path"]).read_text(encoding="utf-8")
                # Skip frontmatter
                lines = content.split("\n")
                body_start = 0
                if lines and lines[0] == "---":
                    for i, line in enumerate(lines[1:], 1):
                        if line == "---":
                            body_start = i + 1
                            break
                body = "\n".join(lines[body_start:]).strip()
                snippet = body[:200].replace("\n", " ")
            except Exception:
                pass

            results.append({
                "name": doc.get("name", name),
                "title": doc.get("title", name),
                "type": doc.get("type", "unknown"),
                "path": doc.get("path", ""),
                "score": round(score, 4),
                "snippet": snippet,
            })

        return results
