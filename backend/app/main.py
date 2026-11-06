from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.app.api.v1.ingestion import router as ingestion_router
from backend.app.api.v1.routes import router
from backend.app.core.config import get_settings
from backend.app.db.session import close_database, get_db
from backend.app.services.resources import Resources, get_resources


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings()
    yield
    if get_resources.cache_info().currsize:
        get_resources().close()
        get_resources.cache_clear()
    close_database()


app = FastAPI(title="SmartRAG Pro", version="0.3.0", lifespan=lifespan)
app.include_router(router)
app.include_router(ingestion_router)


@app.middleware("http")
async def boundary(request: Request, call_next):  # type: ignore[no-untyped-def]
    # The frontend is server-side; do not enable wildcard CORS.
    if request.url.path.startswith("/api/"):
        if request.method in {"POST", "PUT", "PATCH"} and "content-length" not in request.headers:
            return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
        maximum = get_settings().max_upload_bytes + 1024 * 1024
        try:
            if int(request.headers.get("content-length", "0")) > maximum:
                return JSONResponse({"detail": "Request exceeds size limit"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        # Shared rate limiting, using peer IP rather than untrusted forwarded headers.
        # No request body, password, token, or source text is logged.
        try:
            resources = app.dependency_overrides.get(get_resources, get_resources)()
            ip = request.client.host if request.client else "unknown"
            group = "auth" if request.url.path.startswith("/api/v1/auth/") else "api"
            key = f"rate:{group}:{ip}"
            count = await run_in_threadpool(
                resources.redis.eval,
                "local n=redis.call('INCR',KEYS[1]); "
                "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
                1,
                key,
            )
            if int(count) > (20 if group == "auth" else 120):
                return JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
        except Exception:
            return JSONResponse({"detail": "Rate limit service unavailable"}, status_code=503)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready(
    db: Session = Depends(get_db), resources: Resources = Depends(get_resources)
) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1 FROM alembic_version"))
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT 1 FROM checkpoint_migrations LIMIT 1"))
        resources.redis.ping()
        resources.qdrant.get_collections()
        resources.store.ping()
        if not resources.settings.gemini_api_key.get_secret_value():
            raise RuntimeError("Missing generation key")
    except Exception as exc:
        raise HTTPException(503, "A required dependency is unavailable or unconfigured") from exc
    return {"status": "ready"}
