import dramatiq
from dramatiq.brokers.redis import RedisBroker

from backend.app.core.config import get_settings

broker = RedisBroker(url=get_settings().redis_url, namespace="smartrag-ingestion")
dramatiq.set_broker(broker)
