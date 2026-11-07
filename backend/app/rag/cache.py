"""Bounded tenant/model-keyed embedding cache, never retrieval results or source text."""

import hashlib
from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Any

from backend.app.core.telemetry import EVENTS


class VectorCache:
    def __init__(self, capacity: int, ttl: int) -> None:
        self.capacity, self.ttl = capacity, ttl
        self.entries: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self.lock = Lock()

    def key(self, owner: str, fingerprint: str, query: str) -> str:
        return hashlib.sha256(f"{owner}:{fingerprint}:{query}".encode()).hexdigest()

    def get(self, key: str) -> list[float] | None:
        with self.lock:
            record = self.entries.pop(key, None)
            if record and monotonic() - record[0] < self.ttl:
                self.entries[key] = record
                return list(record[1])
            return None

    def put(self, key: str, vector: list[float]) -> None:
        if not self.capacity:
            return
        with self.lock:
            self.entries[key] = (monotonic(), list(vector))
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)


def embed_query(
    resources: Any, owner: str, fingerprint: str, query: str
) -> tuple[list[float], bool]:
    cache = resources.query_cache
    key = cache.key(owner, fingerprint, query)
    vector = cache.get(key)
    if vector is not None:
        EVENTS.labels("embedding.cache", "hit").inc()
        return vector, True
    EVENTS.labels("embedding.cache", "miss").inc()
    vector = resources.embedding.embed_query(query)
    cache.put(key, vector)
    return vector, False
