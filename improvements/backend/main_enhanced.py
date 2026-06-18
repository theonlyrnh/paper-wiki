"""Enhanced main.py with rate limiting and improvements."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from backend.config import CONFIG
from backend.database import init_db
from backend.routers import papers, system, ingest, search, graph, wiki, chat, batch, auth

# Try to import rate limiter (optional dependency)
try:
    from backend.rate_limiter import setup_rate_limiting
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False
    logging.warning("slowapi not installed. Rate limiting disabled. Install with: pip install slowapi")

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

    # Ensure wiki base directory exists (per-user dirs created on demand)
    wiki_base = PROJECT_ROOT / CONFIG["storage"]["wiki_dir"]
    wiki_base.mkdir(parents=True, exist_ok=True)
    logger.info("Wiki base directory ready.")

    if RATE_LIMITING_AVAILABLE:
        logger.info("✅ Rate limiting enabled")
    else:
        logger.warning("⚠️  Rate limiting disabled (slowapi not installed)")

    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Paper Wiki",
    description="基于 LLM 的论文知识库系统",
    version="0.2.0",  # Bumped version
    lifespan=lifespan,
)

# === Middleware ===

# Gzip compression for responses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS (if needed for development)
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:3000"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# Rate limiting (if available)
if RATE_LIMITING_AVAILABLE:
    limiter = setup_rate_limiting(app)
    # Make limiter available to routers
    app.state.limiter = limiter

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
    """Serve the SPA index.html."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "0.2.0",
        "features": {
            "rate_limiting": RATE_LIMITING_AVAILABLE,
            "gzip": True,
        }
    }


if __name__ == "__main__":
    import uvicorn

    host = CONFIG["server"]["host"]
    port = CONFIG["server"]["port"]
    logger.info(f"Starting Paper Wiki v0.2.0 on {host}:{port}")
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT / "backend"), str(FRONTEND_DIR)],
    )
