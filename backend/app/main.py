import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.v1.ingestion import router as ingestion_router
from backend.app.api.v1.routes import router
from backend.app.core import telemetry
from backend.app.core.build_info import build_info
from backend.app.core.config import get_settings
from backend.app.core.errors import SafeErrorResponse
from backend.app.core.telemetry_http import TelemetryHTTP
from backend.app.db.session import close_database, get_db
from backend.app.security.http import HostAndCorsBoundary, RequestBoundary
from backend.app.services.resources import Resources, get_resources


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    telemetry.configure(get_settings())
    yield
    if get_resources.cache_info().currsize:
        get_resources().close()
        get_resources.cache_clear()
    close_database()
    telemetry.shutdown()


app = FastAPI(title="SmartRAG Pro", version=build_info()["version"], lifespan=lifespan)
app.include_router(router)
app.include_router(ingestion_router)


@app.exception_handler(StarletteHTTPException)
async def handled_failure(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return SafeErrorResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


@app.exception_handler(Exception)
async def unexpected_failure(_request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).error(
        "request failed",
        extra={
            "operation": "http.unexpected",
            "safe_metadata": {"error.category": type(exc).__name__},
        },
    )
    return SafeErrorResponse({"detail": "A service is temporarily unavailable"}, status_code=503)


@app.exception_handler(RequestValidationError)
async def validation_failure(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic's default error includes input values, which may contain credentials.
    errors = [{k: error[k] for k in ("loc", "msg", "type")} for error in exc.errors()]
    return SafeErrorResponse({"detail": errors}, status_code=422)


@app.middleware("http")
async def boundary(request: Request, call_next):  # type: ignore[no-untyped-def]
    # The frontend is server-side; do not enable wildcard CORS.
    if request.url.path.startswith("/api/"):
        if get_settings().require_https and request.url.scheme != "https":
            return SafeErrorResponse({"detail": "HTTPS is required"}, status_code=400)
        if request.method in {"POST", "PUT", "PATCH"} and "content-length" not in request.headers:
            return SafeErrorResponse({"detail": "Content-Length is required"}, status_code=411)
        maximum = get_settings().max_upload_bytes + 1024 * 1024
        try:
            length = int(request.headers.get("content-length", "0"))
            if length < 0:
                return SafeErrorResponse({"detail": "Invalid Content-Length"}, status_code=400)
            if length > maximum:
                return SafeErrorResponse({"detail": "Request exceeds size limit"}, status_code=413)
        except ValueError:
            return SafeErrorResponse({"detail": "Invalid Content-Length"}, status_code=400)
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
                return SafeErrorResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
        except Exception:
            return SafeErrorResponse({"detail": "Rate limit service unavailable"}, status_code=503)
    response = await call_next(request)
    return response


# Outermost boundary also covers early rate/validation/host failures.
app.add_middleware(HostAndCorsBoundary)
app.add_middleware(RequestBoundary)
app.add_middleware(TelemetryHTTP)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    if not get_settings().metrics_enabled:
        raise HTTPException(404, "Not found")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "alive", **build_info()}


@app.get("/health/ready", tags=["health"])
def ready(
    db: Session = Depends(get_db), resources: Resources = Depends(get_resources)
) -> dict[str, str]:
    try:
        checks: dict[str, Callable[[], Any]] = {
            "database": lambda: db.execute(text("SELECT 1 FROM alembic_version")),
            "redis": resources.redis.ping,
            "qdrant": resources.qdrant.get_collections,
            "storage": resources.store.ping,
        }
        for name, check in checks.items():
            try:
                with telemetry.operation("health." + name):
                    check()
                telemetry.DEPENDENCY.labels(name).set(1)
            except Exception:
                telemetry.DEPENDENCY.labels(name).set(0)
                raise
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT 1 FROM checkpoint_migrations LIMIT 1"))
        if not resources.settings.gemini_api_key.get_secret_value():
            raise RuntimeError("Missing generation key")
    except Exception as exc:
        raise HTTPException(503, "A required dependency is unavailable or unconfigured") from exc
    return {"status": "ready"}
