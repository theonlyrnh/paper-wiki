"""Paper Wiki — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.config import CONFIG
from backend.database import init_db
from backend.routers import papers, system, ingest, search, graph, wiki, chat, batch, auth
from backend.services.ingest_maintenance import cleanup_stale_tasks

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready.")
    try:
        stale_result = await cleanup_stale_tasks()
    except Exception as exc:
        logger.warning("Stale ingestion cleanup skipped: %s", exc)
    else:
        if stale_result["papers_marked_failed"] or stale_result["ingest_tasks_marked_failed"]:
            logger.warning(
                "Marked stale ingestion states failed: papers=%s, ingest_tasks=%s, cutoff=%s",
                stale_result["papers_marked_failed"],
                stale_result["ingest_tasks_marked_failed"],
                stale_result["cutoff"],
            )

    # Ensure wiki base directory exists (per-user dirs created on demand)
    wiki_base = PROJECT_ROOT / CONFIG["storage"]["wiki_dir"]
    wiki_base.mkdir(parents=True, exist_ok=True)
    logger.info("Wiki base directory ready.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Paper Wiki",
    description="基于 LLM 的论文知识库系统",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# === API Routers ===
# Auth router first (login/register are public)
app.include_router(auth.router)

# Protected routers
app.include_router(papers.router)
app.include_router(system.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(wiki.router)
app.include_router(chat.router)
app.include_router(batch.router)

# === Static Files (Frontend) ===
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    """Serve the SPA index.html — never cached so JS version bumps take effect immediately."""
    return FileResponse(
        str(FRONTEND_DIR / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


if __name__ == "__main__":
    import uvicorn

    host = CONFIG["server"]["host"]
    port = CONFIG["server"]["port"]
    logger.info(f"Starting Paper Wiki on {host}:{port}")
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT / "backend"), str(FRONTEND_DIR)],
    )
