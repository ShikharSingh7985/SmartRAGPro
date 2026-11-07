"""Explicit isolated load experiment; never a normal application's fake-provider mode.

Run with pytest tests/benchmark_load.py against disposable services for meaningful
DB concurrency. Model latency is an explicitly simulated 30 ms; embeddings are test
vocabulary vectors. This is not live Gemini performance or a production-scale claim.
"""

import json
import os
import platform
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psutil
import pytest

from backend.app.core.security import hasher, issue_token
from backend.app.models.entities import (
    Conversation,
    ConversationDocument,
    Document,
    IngestionJob,
    User,
)
from backend.app.workers.ingestion import process_one


@pytest.mark.parametrize("concurrency", [1, 5, 10, 25])
def test_warm_chat_load(stack, pdf, concurrency):
    client, factory, resources = stack
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Run the load experiment against disposable PostgreSQL services")
    users = []
    setup = time.perf_counter()
    for i in range(concurrency):
        with factory() as db:
            owner = User(
                email=f"load-{i}@example.com", password_hash=hasher.hash("isolated-load-password")
            )
            db.add(owner)
            db.flush()
            identifier = uuid4()
            key = f"{owner.id}/{identifier}.pdf"
            resources.store.put(key, pdf)
            document = Document(
                id=identifier,
                user_id=owner.id,
                object_key=key,
                filename="load.pdf",
                extraction_mode="text-first",
            )
            db.add(document)
            db.flush()
            job = IngestionJob(document_id=identifier)
            db.add(job)
            db.commit()
            assert process_one(db, resources, job.id)
            assert db.get(Document, identifier).status == "ready"
            chat = Conversation(user_id=owner.id)
            db.add(chat)
            db.flush()
            db.add(ConversationDocument(conversation_id=chat.id, document_id=identifier))
            db.commit()
            users.append(
                (
                    str(chat.id),
                    {"Authorization": "Bearer " + issue_token(owner, resources.settings)},
                )
            )
    ingestion_seconds = time.perf_counter() - setup

    def model(*args):
        time.sleep(0.03)
        return "Alpha revenue is 42 million dollars. [1]"

    resources._generator.answer.side_effect = model
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stopped = threading.Event()

    def sample():
        while not stopped.wait(0.025):
            peak[0] = max(peak[0], process.memory_info().rss)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    cpu_start = process.cpu_times()

    def session(user):
        chat, headers = user
        points = []
        for _ in range(4):
            start = time.perf_counter()
            response = client.post(
                f"/api/v1/conversations/{chat}/messages",
                headers=headers,
                json={"content": "What is Alpha revenue?", "request_id": str(uuid4())},
            )
            points.append({"seconds": time.perf_counter() - start, "status": response.status_code})
        return points

    start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            points = [point for result in pool.map(session, users) for point in result]
    finally:
        stopped.set()
        sampler.join(timeout=2)
    wall = time.perf_counter() - start
    cpu_end = process.cpu_times()
    durations = sorted(point["seconds"] for point in points)

    def percentile(p):
        return durations[min(len(durations) - 1, round((len(durations) - 1) * p))]

    failures = sum(point["status"] != 201 for point in points)
    root = Path(os.environ.get("LOAD_RESULTS_DIR", "evaluation/release/load"))
    root.mkdir(parents=True, exist_ok=True)
    result = {
        "concurrency": concurrency,
        "requests": len(points),
        "failures": failures,
        "failure_rate": failures / len(points),
        "throughput_rps": len(points) / wall,
        "wall_seconds": wall,
        "mean_seconds": statistics.mean(durations),
        "p50_seconds": percentile(0.5),
        "p95_seconds": percentile(0.95) if len(points) >= 20 else None,
        "p99_seconds": percentile(0.99) if len(points) >= 100 else None,
        "peak_process_rss_bytes": peak[0],
        "cpu_seconds": cpu_end.user + cpu_end.system - cpu_start.user - cpu_start.system,
        "setup_and_ingestion_seconds": ingestion_seconds,
        "pages": 2 * concurrency,
        "points": points,
        "configuration": {
            "provider": (
                "isolated test doubles, simulated 30ms model; 8-dimensional test embeddings"
            ),
            "transport": (
                "in-process FastAPI ASGI; real PostgreSQL/Qdrant/Redis/S3 when TEST_* configured"
            ),
            "context": "warm selected PDFs; 4 sequential turns per distinct user; tracing disabled",
            "ttft": None,
            "provider_throttling": None,
            "billing_cost": None,
        },
        "hardware": {
            "os": platform.system(),
            "machine": platform.machine(),
            "logical_cpu": psutil.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total,
        },
    }
    (root / f"users-{concurrency}.json").write_text(json.dumps(result, indent=2) + "\n")
    assert failures == 0, result
