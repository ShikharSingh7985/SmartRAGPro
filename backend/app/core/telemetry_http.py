import logging
import time

from opentelemetry.trace import StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.errors import SafeErrorResponse
from backend.app.core.telemetry import (
    ACTIVE,
    HTTP_SECONDS,
    REQUESTS,
    new_request,
    operation,
    request_id,
)


class TelemetryHTTP:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        identifier = new_request()
        token = request_id.set(identifier)
        started = time.perf_counter()
        status = 500
        response_started = False
        ACTIVE.inc()
        method = scope.get("method", "OTHER")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
            method = "OTHER"

        async def correlated(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", identifier.encode())
                ]
            await send(message)

        # Do not trust client baggage or arbitrary correlation IDs.
        with operation(
            "http.request",
            details={"http.request.method": method, "request.id": identifier},
        ) as span:
            try:
                await self.app(scope, receive, correlated)
            except Exception as exc:
                # Starlette's outer error handler runs after our context unwinds.
                # Handle an unsent response here so status and correlation stay exact.
                logging.getLogger(__name__).error(
                    "request failed",
                    extra={
                        "operation": "http.unexpected",
                        "safe_metadata": {"error.category": type(exc).__name__},
                    },
                )
                if response_started:
                    raise
                await SafeErrorResponse(
                    {"detail": "A service is temporarily unavailable"}, status_code=503
                )(scope, receive, correlated)
            finally:
                route = getattr(scope.get("route"), "path", "unmatched")
                method = scope.get("method", "OTHER")
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                    method = "OTHER"
                REQUESTS.labels(method, route, str(status)).inc()
                HTTP_SECONDS.labels(method, route).observe(time.perf_counter() - started)
                ACTIVE.dec()
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(StatusCode.ERROR)
                request_id.reset(token)
