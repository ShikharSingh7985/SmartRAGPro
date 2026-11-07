from typing import Any

from fastapi.responses import JSONResponse

from backend.app.core.telemetry import request_id


class ProviderUnavailable(RuntimeError):
    """Retryable provider failure after a bounded attempt budget; never stores private errors."""


def retryable_provider_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    for _ in range(4):
        if current is None:
            break
        if isinstance(current, TimeoutError) or type(current).__name__ in {
            "ResourceExhausted",
            "ServiceUnavailable",
            "DeadlineExceeded",
            "ReadTimeout",
            "ConnectTimeout",
        }:
            return True
        if getattr(current, "code", None) in {429, 500, 502, 503, 504} or getattr(
            current, "status_code", None
        ) in {429, 500, 502, 503, 504}:
            return True
        current = current.__cause__
    return False


class SafeErrorResponse(JSONResponse):
    def __init__(self, content: Any, status_code: int = 500, headers: Any = None) -> None:
        detail = content.get("detail", "Request failed")
        code = (
            "authentication"
            if status_code == 401
            else "rate_limited"
            if status_code == 429
            else "dependency_unavailable"
            if status_code >= 500
            else "request_rejected"
        )
        super().__init__(
            {
                "detail": detail,
                "error": {"code": code, "retryable": status_code in {429, 502, 503, 504}},
                "request_id": request_id.get(),
            },
            status_code=status_code,
            headers=headers,
        )
