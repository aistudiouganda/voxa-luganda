"""
Voxa Luganda — AI Speech Transcription API
FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import time

from core.config import settings
from core.database import init_db, check_db_connection

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Voxa Luganda API...")

    # Create all DB tables
    await init_db()

    # Pre-load model manager (lazy — won't load Whisper yet)
    from services.model_manager import model_manager
    await model_manager.initialize()

    logger.info("✅ Voxa Luganda API ready")
    yield

    # Cleanup
    from services.model_manager import model_manager as mm
    await mm.cleanup()
    logger.info("Voxa Luganda API shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI Speech Transcription API for Luganda and East African Languages",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS — allow frontend on localhost:3000 and production domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{ms:.1f}"
    return response


# Import routers after app is created to avoid circular imports
from api.routes import transcripts, auth, users, exports, vocabulary
from api.routes import websocket

app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["Auth"])
app.include_router(users.router, prefix=f"{settings.API_V1_PREFIX}/users", tags=["Users"])
app.include_router(transcripts.router, prefix=f"{settings.API_V1_PREFIX}/transcripts", tags=["Transcripts"])
app.include_router(exports.router, prefix=f"{settings.API_V1_PREFIX}/exports", tags=["Exports"])
app.include_router(vocabulary.router, prefix=f"{settings.API_V1_PREFIX}/vocabulary", tags=["Vocabulary"])
app.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])

# Serve local audio files (dev only)
if settings.STORAGE_BACKEND == "local" and os.path.isdir(settings.LOCAL_STORAGE_PATH):
    app.mount("/storage", StaticFiles(directory=settings.LOCAL_STORAGE_PATH), name="storage")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    db_ok = await check_db_connection()
    from services.model_manager import model_manager
    return {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": "connected" if db_ok else "disconnected",
        "db_backend": settings.DATABASE_URL.split("+")[0],
        "storage": settings.STORAGE_BACKEND,
        "models": model_manager.status(),
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )
