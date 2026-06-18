"""Hybrid search service — combines BM25 keyword search with vector semantic search."""

import logging
from typing import Optional

from backend.services.search_engine import WikiSearchEngine
from backend.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# RRF constant (standard value from literature)
RRF_K = 60


class HybridSearch:
    """
    Hybrid search combining BM25 keyword matching and vector semantic search.

    Uses Reciprocal Rank Fusion (RRF) to merge results from both methods.
    RRF formula: score(d) = Σ 1 / (k + rank_i(d))
    where k=60 is a standard constant.
    """

    def __init__(self):
        self.bm25 = WikiSearchEngine()
        self.vector_store = get_vector_store()

    def reindex(self):
        """Rebuild both BM25 index and vector store."""
        self.bm25.build_index()
        logger.info("BM25 index rebuilt")
        # Vector reindex is handled separately via /api/search/reindex-vectors

    async def search(
        self,
        query: str,
        top_k: int = 20,
        use_bm25: bool = True,
        use_vector: bool = True,
        user_id: int = None,
    ) -> list[dict]:
        """
        Perform hybrid search.

        Args:
            query: Search query string.
            top_k: Number of results to return.
            use_bm25: Whether to include BM25 keyword results.
            use_vector: Whether to include vector semantic results.

        Returns:
            List of search results, sorted by fused RRF score.
        """
        bm25_results = []
        vector_results = []

        # Fetch BM25 results
        if use_bm25:
            try:
                bm25_results = self.bm25.search(query, top_k=30, user_id=user_id)
            except Exception as e:
                logger.warning(f"BM25 search failed: {e}")

        # Fetch vector results
        if use_vector:
            try:
                vector_results = await self.vector_store.search(query, top_k=30, user_id=user_id)
            except Exception as e:
                logger.warning(f"Vector search failed: {e}")

        # If both methods failed, return empty
        if not bm25_results and not vector_results:
            return []

        # If only one method returned results, use it directly
        if not bm25_results:
            return self._enrich_results(vector_results[:top_k], source="vector")
        if not vector_results:
            return self._enrich_results(bm25_results[:top_k], source="bm25")

        # Fuse results using RRF
        fused = self._rrf_fusion(bm25_results, vector_results)

        return fused[:top_k]

    def _rrf_fusion(
        self,
        bm25_results: list[dict],
        vector_results: list[dict],
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion.

        Combines two ranked lists into one using:
            score(d) = 1/(k + rank_bm25) + 1/(k + rank_vector)
        where missing rank is treated as infinity (contributes 0).
        """
        # Build rank maps: name -> rank (1-based)
        bm25_ranks = {r["name"]: i + 1 for i, r in enumerate(bm25_results)}
        vector_ranks = {r["name"]: i + 1 for i, r in enumerate(vector_results)}

        # Collect all candidate names
        all_names = set(bm25_ranks.keys()) | set(vector_ranks.keys())

        # Compute RRF scores
        scores = {}
        sources = {}
        for name in all_names:
            score = 0.0
            matched_sources = []

            if name in bm25_ranks:
                score += 1.0 / (RRF_K + bm25_ranks[name])
                matched_sources.append("bm25")
            if name in vector_ranks:
                score += 1.0 / (RRF_K + vector_ranks[name])
                matched_sources.append("vector")

            scores[name] = score
            sources[name] = matched_sources

        # Sort by RRF score descending
        ranked_names = sorted(scores.keys(), key=lambda n: -scores[n])

        # Build result list, pulling metadata from whichever source has it
        results = []
        bm25_by_name = {r["name"]: r for r in bm25_results}
        vector_by_name = {r["name"]: r for r in vector_results}

        for name in ranked_names:
            # Prefer BM25 for metadata (it has richer snippets)
            base = bm25_by_name.get(name) or vector_by_name.get(name, {})
            result = {
                "name": name,
                "title": base.get("title", name),
                "type": base.get("type", "unknown"),
                "score": round(scores[name], 6),
                "snippet": base.get("snippet", ""),
                "search_sources": sources[name],
                "bm25_rank": bm25_ranks.get(name),
                "vector_rank": vector_ranks.get(name),
            }
            results.append(result)

        return results

    def _enrich_results(self, results: list[dict], source: str) -> list[dict]:
        """Add source metadata to results when only one method returns data."""
        for r in results:
            r["search_sources"] = [source]
            r["score"] = round(r.get("score", 0), 6)
            if source == "bm25":
                r["bm25_rank"] = results.index(r) + 1
                r["vector_rank"] = None
            else:
                r["bm25_rank"] = None
                r["vector_rank"] = results.index(r) + 1
        return results


# Global singleton
_search = None


def get_hybrid_search() -> HybridSearch:
    """Get the global HybridSearch instance."""
    global _search
    if _search is None:
        _search = HybridSearch()
    return _search
