"""Vector store — LanceDB-based storage and search for wiki page embeddings."""

import json
import logging
from pathlib import Path
from typing import Optional

import lancedb
import pyarrow as pa

from backend.config import CONFIG
from backend.services.embedding import embed_texts, embed_query, DIMENSIONS, is_configured

logger = logging.getLogger(__name__)

VECTORS_DIR = Path(__file__).parent.parent.parent / CONFIG["storage"]["vectors_dir"]
TABLE_NAME = "wiki_pages"


class VectorStore:
    """LanceDB vector store for wiki page embeddings."""

    def __init__(self):
        self.db = None
        self.table = None
        self._initialized = False

    def _ensure_init(self):
        """Initialize LanceDB connection and table."""
        if self._initialized:
            return

        VECTORS_DIR.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(VECTORS_DIR))

        # Define schema
        schema = pa.schema([
            pa.field("name", pa.string()),
            pa.field("type", pa.string()),
            pa.field("title", pa.string()),
            pa.field("content", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), DIMENSIONS)),
            pa.field("content_hash", pa.string()),
        ])

        # Open or create table
        try:
            self.table = self.db.open_table(TABLE_NAME)
        except Exception:
            self.table = self.db.create_table(TABLE_NAME, schema=schema)

        self._initialized = True
        logger.info(f"VectorStore initialized: {VECTORS_DIR}, table={TABLE_NAME}")

    def upsert(self, name: str, page_type: str, title: str, content: str, content_hash: str):
        """
        Insert or update a wiki page's embedding.

        This is a sync wrapper that generates the embedding synchronously.
        For async usage, prefer upsert_async().
        """
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, we need to handle this differently
            # Use a thread to run the async embedding call
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._upsert_impl(name, page_type, title, content, content_hash))
                future.result()
        else:
            loop.run_until_complete(self._upsert_impl(name, page_type, title, content, content_hash))

    async def upsert_async(self, name: str, page_type: str, title: str, content: str, content_hash: str):
        """Async version of upsert."""
        await self._upsert_impl(name, page_type, title, content, content_hash)

    async def _upsert_impl(self, name: str, page_type: str, title: str, content: str, content_hash: str):
        """Internal implementation for upsert."""
        self._ensure_init()

        if not is_configured():
            logger.warning("Embedding not configured, skipping vector upsert")
            return

        # Truncate content for embedding (most models have ~8K token limit)
        embed_text = f"{title}\n\n{content}"[:6000]

        embeddings = await embed_texts([embed_text])
        if not embeddings:
            return

        vector = embeddings[0]

        # Remove existing entry if present
        try:
            self.table.delete(f'name = "{name}"')
        except Exception:
            pass  # Table might be empty or name not found

        # Insert new entry
        data = [{
            "name": name,
            "type": page_type,
            "title": title,
            "content": content[:500],  # Store truncated content for snippets
            "vector": vector,
            "content_hash": content_hash,
        }]
        self.table.add(data)
        logger.info(f"Vector upsert: {name} ({page_type})")

    def delete(self, name: str):
        """Delete a wiki page's embedding."""
        self._ensure_init()
        try:
            self.table.delete(f'name = "{name}"')
            logger.info(f"Vector delete: {name}")
        except Exception as e:
            logger.warning(f"Vector delete failed for {name}: {e}")

    async def search(self, query: str, top_k: int = 30, user_id: int = None) -> list[dict]:
        """Search wiki pages by semantic similarity, filtered by user_id."""
        self._ensure_init()

        if not is_configured():
            return []

        try:
            count = self.table.count_rows()
            if count == 0:
                return []
        except Exception:
            return []

        query_vec = await embed_query(query)

        # Fetch more results to account for filtering
        fetch_k = top_k * 3 if user_id else top_k
        results = (
            self.table
            .search(query_vec)
            .limit(fetch_k)
            .to_list()
        )

        # Filter by user_id prefix
        if user_id is not None:
            prefix = f"u{user_id}_"
            results = [r for r in results if r.get("name", "").startswith(prefix)]
            # Strip prefix from name for downstream compatibility
            for r in results:
                r["name"] = r["name"][len(prefix):]
                # Normalize type to singular
                ptype = r.get("type", "")
                _PTYPE = {"sources": "source", "entities": "entity", "concepts": "concept"}
                if ptype in _PTYPE:
                    r["type"] = _PTYPE[ptype]

        results = results[:top_k]

        search_results = []
        for r in results:
            # LanceDB returns _distance (L2 distance); convert to similarity score
            distance = r.get("_distance", 1.0)
            # Convert L2 distance to 0-1 similarity (approximate)
            score = 1.0 / (1.0 + distance)

            search_results.append({
                "name": r["name"],
                "title": r["title"],
                "type": r["type"],
                "score": round(score, 4),
                "snippet": r.get("content", "")[:200].replace("\n", " "),
            })

        return search_results

    def stats(self) -> dict:
        """Get vector store statistics."""
        self._ensure_init()
        try:
            count = self.table.count_rows()
        except Exception:
            count = 0

        return {
            "total_vectors": count,
            "dimensions": DIMENSIONS,
            "model": CONFIG.get("embedding", {}).get("model", "unknown"),
            "configured": is_configured(),
        }


# Global singleton
_store = None


def get_vector_store() -> VectorStore:
    """Get the global VectorStore instance."""
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
