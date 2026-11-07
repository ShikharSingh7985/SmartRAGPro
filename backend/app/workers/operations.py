"""Process-local metrics/export threads start after Dramatiq forks."""

import threading
import time

from dramatiq import Middleware
from redis import Redis

from backend.app.core.config import get_settings
from backend.app.core.telemetry import HEARTBEAT, configure, shutdown, start_metrics


class OperationsMiddleware(Middleware):
    def after_process_boot(self, broker):  # type: ignore[no-untyped-def]
        settings = get_settings()
        configure(settings)
        start_metrics(settings)

        def heartbeat() -> None:
            connection = Redis.from_url(settings.redis_url, socket_timeout=3)
            while True:
                try:
                    connection.set("smartrag:health:worker", str(time.time()), ex=120)
                    HEARTBEAT.labels("worker").set(time.time())
                except Exception:
                    pass
                time.sleep(15)

        threading.Thread(target=heartbeat, daemon=True, name="worker-health").start()

    def before_worker_shutdown(self, broker, worker):  # type: ignore[no-untyped-def]
        shutdown()
