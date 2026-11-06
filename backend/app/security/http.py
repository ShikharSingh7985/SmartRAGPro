"""Count actual ASGI body bytes, including requests with false declared lengths."""

from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.config import get_settings


class HostAndCorsBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        cors = CORSMiddleware(
            self.app,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )
        await TrustedHostMiddleware(cors, allowed_hosts=settings.allowed_hosts)(
            scope, receive, send
        )


class RequestBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        total = 0
        maximum = get_settings().max_upload_bytes + 1024 * 1024
        rejected = False
        rejection_sent = False

        async def limited_receive() -> Message:
            nonlocal total, rejected
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > maximum:
                    rejected = True
                    # Parser sees disconnect; suppress its response and emit our own 413.
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal rejection_sent
            if rejected:
                if message["type"] == "http.response.start":
                    message = {"type": "http.response.start", "status": 413, "headers": []}
                elif message["type"] == "http.response.body":
                    if rejection_sent:
                        return
                    rejection_sent = True
                    message = {"type": "http.response.body", "body": b"Request exceeds size limit"}
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"cache-control", b"no-store"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            (
                                b"default-src 'none'; frame-ancestors 'none'; "
                                b"script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
                                b"style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
                                b"img-src https://fastapi.tiangolo.com data:; connect-src 'self'"
                                if scope.get("path") in {"/docs", "/redoc"}
                                else b"default-src 'none'; frame-ancestors 'none'"
                            ),
                        ),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                if scope.get("scheme") == "https":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
