# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://example.com/keepachangelog) and this project adheres to [Semantic Versioning](https://example.com/semver).

## [0.3.0] - 2026-06-17

### Added
- Ingest stability system: DB migration (wiki_pages UNIQUE by user_id/type/name), stale task cleanup, WAL mode, busy_timeout=30s
- LLM retry with exponential backoff (3 attempts, 5/15/45s delays) for timeout/connect errors/429/5xx
- Empty LLM response detection with automatic retry (reasoning-only outputs)
- Wiki filename sanitization — prevents "unknown.md" and other bad filenames from being created
- Title extraction from YAML frontmatter for accurate wiki page titles
- Cleanup script for legacy unknown.md files (`scripts/cleanup_unknown.py`)
- Diagnostic script for ingestion health (`scripts/diagnose_ingest.py`)
- Regression test suite (7 tests covering ingest stability, search, storage, evidence cache)
- `ingest_queue` table expanded with attempt tracking, locking, heartbeat fields for future worker
- `wiki_pages` table: added `indexed_hash` and `indexed_at` for incremental vector indexing

### Changed
- **LLM context window**: increased from 128K to 1,000,000 tokens (DeepSeek-V4-Pro)
- **LLM max output**: 8,192 → 393,216 tokens (384K)
- **Paper truncation**: 50K → 1,875,000 chars (~625K tokens), utilizing 75% of context
- **Wiki context truncation**: 8K → 250,000 chars (~83K tokens)
- **Language enforcement**: All LLM prompts now require Chinese output for titles, descriptions, abstracts, findings, and wiki content
- **LLM generate prompt**: Added filename naming rules (English slugs, no "unknown"/"untitled")
- SQLite PRAGMAs: WAL journal mode, busy_timeout=30s, synchronous=NORMAL, foreign_keys=ON
- Ingestion concurrency: parse=1, ingest=1, LLM=1, embedding=2 (semaphore-based)
- MinerU upgraded from `magic-pdf` 1.3.12 to `mineru` 3.3.1 with PyTorch 2.12 + CUDA 12.6
- Environment optimization: backend conda env reduced from 6.9G to 881M (removed unused GPU libraries)

### Fixed
- `UNIQUE constraint failed: wiki_pages.name` — schema migrated to per-user/type/name uniqueness
- `database is locked` — WAL mode + 30s busy_timeout resolves SQLite contention
- LLM returning empty content (thinking-only responses) now detected and retried
- `executescript` resetting connection PRAGMAs — re-applied after schema creation
- `datetime.utcnow()` deprecation warning in diagnostic scripts
- MinerU API response format compatibility (new v2 `results` field)

### Security
- Enhanced .gitignore to exclude internal docs, planning files, and local-only scripts
- publish-safe.sh allowlist-based upload workflow (never contains real sensitive values)

## [0.2.0] - 2026-06-17

### Added
- Multi-user login system with authentication
- User-level data isolation (papers, wiki pages, vectors per user)
- Light/dark theme toggle with persistent user preferences
- User model configuration (custom LLM/Embedding settings)
- PDF slice rendering in search results with clickable references
- Chat system with knowledge graph references
- Knowledge graph visualization with node/edge filtering
- Batch paper import functionality
- Rate limiting and input validation for API endpoints
- LLM prompt injection protection
- File upload validation (magic bytes, size limits)
- Toast notification system
- Global keyboard shortcuts (Cmd+K for search)
- Skeleton loading states
- Design tokens CSS system

### Changed
- Reorganized directory structure (moved design docs to docs/design/, reviews to docs/reviews/)
- Moved sensitive docs to docs/security/
- Enhanced search with hybrid BM25 + vector search (RRF fusion)
- Improved PDF slice scoring (relative ranking based on match quality)
- Added credentials: 'include' to all fetch() calls for proper auth
- Graph rendering optimization (default weight filter 4.0, precomputeLayout)
- Faster graph simulation cooling (0.985 → 0.96)

### Fixed
- Graph text rendering (outline stroke instead of shadow for clarity)
- Search results not returning for Chinese queries (Embedding API key refresh)
- PDF slices not loading (missing credentials in fetch)
- Graph not updating after paper deletion (cache invalidation)
- Chat references showing duplicate entries (deduplication by name)
- Chat references with u{uid}_ prefix (normalization)

### Security
- Implemented AI_UPLOAD_SECURITY.md guidelines
- Added scan_sensitive.py for pre-upload verification
- Upload Guard extension for automatic sensitive info detection
- Sanitization pipeline: API URLs, IPs, domains, paths, passwords

## [0.1.0] - 2026-06-15

### Added
- Initial release of Paper Wiki
- PDF parsing with MinerU integration
- Two-step LLM ingestion pipeline (analyze → generate)
- Wiki page generation with YAML frontmatter
- BM25 search with jieba tokenization
- Knowledge graph construction (NetworkX)
- Vector store with LanceDB (GLM-Embedding-3, 2048d)
- SPA frontend with hash routing
- Markdown rendering with KaTeX math support
