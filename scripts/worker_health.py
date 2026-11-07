"""Check process heartbeat; durable job leases separately indicate stalled work."""

import time

from redis import Redis

from backend.app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    try:
        with Redis.from_url(settings.redis_url, socket_timeout=3) as connection:
            stamp = connection.get("smartrag:health:" + settings.service_role)
            if stamp is None or time.time() - float(stamp) > 90:
                raise ValueError("Stale heartbeat")
    except Exception:
        raise SystemExit("Service heartbeat unavailable") from None


if __name__ == "__main__":
    main()
