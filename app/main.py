import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.container import Container
from app.core.exceptions import register_exception_handlers
from app.router.routes import api_router

settings = get_settings()
container = Container()

BASE_DIR = Path(__file__).resolve().parent
Path(settings.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
LOG_FILE = BASE_DIR.parent / "uvicorn-service.log"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


# --------------------------------------------------------------------------- logging
class ShutdownFilter(logging.Filter):
    """Hide noisy CancelledError traces printed by uvicorn on shutdown."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "asyncio.exceptions.CancelledError" not in record.getMessage()


def setup_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT)

    # rotating file: 10 MB x 5 backups, so the log never grows unbounded
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format=LOG_FORMAT,
        handlers=[file_handler, stream_handler],
        force=True,
    )

    # uvicorn loggers don't propagate to root, so attach the file handler explicitly
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.setLevel(logging.INFO)
        if file_handler not in uv_logger.handlers:
            uv_logger.addHandler(file_handler)

    logging.getLogger("uvicorn.error").addFilter(ShutdownFilter())
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )


setup_logging()
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = container.db()

    # fail fast: don't start serving traffic if the DB is unreachable
    if not await db.ping():
        raise RuntimeError("Database is unreachable, aborting startup")
    logger.info("✅ Application started (%s v%s)", settings.APP_NAME, settings.VERSION)

    yield

    logger.info("🛑 Shutting down application...")
    try:
        await db.close()
        logger.info("✅ Database disconnected")
    except Exception:
        logger.exception("❌ Error during shutdown")


# --------------------------------------------------------------------------- app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    docs_url="/api/docs" if settings.DEBUG else None,  # hide Swagger in production
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)
app.container = container

register_exception_handlers(app)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),  # explicit list; never "*" with credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
# downloaded reels/thumbnails: /media/reels/<shortcode>.mp4, /media/thumbs/<shortcode>.jpg
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")


# --------------------------------------------------------------------------- service routes
@app.get("/api", include_in_schema=False)
async def root():
    return {"message": f"{settings.APP_NAME} API", "version": settings.VERSION, "status": "running"}


@app.get("/api/health", tags=["health"])
async def health():
    """Liveness: process is up."""
    return {"status": "healthy"}


@app.get("/api/health/ready", tags=["health"])
async def ready(response: Response):
    """Readiness: dependencies (DB) are reachable. Use for load balancer / k8s probes."""
    if not await container.db().ping():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "down"}
    return {"status": "ready", "database": "up"}


app.include_router(api_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)