"""Actual SQL/Qdrant hot retrieval and real embedding-cache cold/warm experiment.

Only the disposable smartrag_test database is accepted. No fake provider latency.
"""

import json
import os
import platform
import secrets
import threading
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, uuid4, uuid5

import psutil
from alembic import command
from alembic.config import Config
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.conversations.evidence import retrieve
from backend.app.conversations.memory import infer_topic, resolve
from backend.app.core.config import get_settings
from backend.app.core.security import hasher
from backend.app.models.entities import Document, User
from backend.app.rag.cache import embed_query
from backend.app.rag.lexical import store_chunk
from backend.app.rag.types import embedding_fingerprint
from backend.app.services.resources import Resources
from evaluation.dataset import load
from evaluation.metrics import distribution


def main():
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.endswith("/smartrag_test") or not url.startswith("postgresql+psycopg://"):
        raise SystemExit("Set TEST_DATABASE_URL to a disposable PostgreSQL smartrag_test database")
    dataset = load()
    retrieval = json.loads(Path("evaluation/results/retrieval.json").read_text())
    if retrieval["dataset_sha256"] != dataset.fingerprint():
        raise SystemExit("Dataset changed; rerun retrieval first")
    from hashlib import sha256

    settings = get_settings()
    signature = sha256(
        (
            dataset.fingerprint() + settings.embedding_model + str(settings.embedding_dimensions)
        ).encode()
    ).hexdigest()
    vectors = json.loads((Path("evaluation/.cache") / (signature + ".json")).read_text())
    config = Config("alembic.ini")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    command.upgrade(config, "head")
    print("Disposable database migrations ready", flush=True)
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    get_settings.cache_clear()
    engine = create_engine(
        url,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000",
        },
    )
    collection = "smartrag_perf_" + uuid4().hex[:12]
    settings = settings.model_copy(update={"qdrant_collection": collection})
    resources = Resources.__new__(Resources)
    resources.settings = settings
    resources._embedding = None
    resources.qdrant = QdrantClient(
        url=os.environ.get("TEST_QDRANT_URL", "http://localhost:56333"), timeout=30
    )
    resources.qdrant.create_collection(
        collection,
        vectors_config=qm.VectorParams(
            size=settings.embedding_dimensions, distance=qm.Distance.COSINE
        ),
    )
    print("Isolated Qdrant collection ready", flush=True)
    owner = uuid4()
    documents = {}
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stop = threading.Event()

    def monitor():
        while not stop.wait(0.01):
            peak[0] = max(peak[0], process.memory_info().rss)

    thread = threading.Thread(target=monitor)
    thread.start()
    try:
        with Session(engine) as db:
            db.add(
                User(
                    id=owner,
                    email=f"synthetic-benchmark-{owner}@example.com",
                    password_hash=hasher.hash(secrets.token_urlsafe(48)),
                )
            )
            db.flush()
            for source in sorted({c.document_id for c in dataset.chunks}):
                doc = Document(
                    id=uuid4(),
                    user_id=owner,
                    filename=source + ".pdf",
                    object_key="synthetic-benchmark/" + uuid4().hex,
                    status="ready",
                    page_count=6,
                    chunk_count=6,
                    active_run=str(uuid4()),
                )
                db.add(doc)
                documents[source] = doc
            db.flush()
            points = []
            for chunk, vector in zip(dataset.chunks, vectors["vectors"], strict=True):
                doc = documents[chunk.document_id]
                identity = str(uuid5(NAMESPACE_URL, collection + chunk.id))
                payload = {
                    "user_id": str(owner),
                    "document_id": str(doc.id),
                    "filename": chunk.filename,
                    "run_token": doc.active_run,
                    "text": chunk.text,
                    "page": chunk.page,
                    "page_end": chunk.page,
                    "chunk_id": chunk.id,
                    "content_type": chunk.content_type,
                }
                store_chunk(db, identity, payload)
                points.append(qm.PointStruct(id=identity, vector=vector, payload=payload))
            db.commit()
            print("Synthetic SQL index ready", flush=True)
            resources.qdrant.upsert(collection, points=points, wait=True)
            # Real uncached embedding followed by a real cache hit; excludes generation.
            fingerprint = embedding_fingerprint(settings)
            cold = []
            for label in ["cold", "warm"]:
                started = perf_counter()
                _, hit = embed_query(resources, str(owner), fingerprint, "What is overfitting?")
                cold.append(
                    {"state": label, "milliseconds": (perf_counter() - started) * 1000, "hit": hit}
                )
                print(f"Real embedding cache probe: {label}", flush=True)
            # Preload recorded REAL Google query embeddings. Hot service timings exclude
            # provider time, explicitly; no embedding test double is constructed.
            rewritten = []
            for query, vector in zip(dataset.queries, vectors["queries"], strict=True):
                topic = infer_topic(query.context[-1]["content"]) if query.context else ""
                text = resolve(query.text, topic, {}, query.context, [])["rewritten_question"]
                rewritten.append(text)
                resources.query_cache.put(
                    resources.query_cache.key(str(owner), fingerprint, text), vector
                )
            rows = []
            cpu = process.cpu_times()
            for mode in ["dense", "bm25", "hybrid", "hybrid_rerank"]:
                resources.settings.retrieval_mode = mode
                for query, text in zip(dataset.queries, rewritten, strict=True):
                    plan = {}
                    started = perf_counter()
                    evidence = retrieve(
                        resources,
                        owner,
                        [documents[d] for d in query.document_ids],
                        text,
                        plan,
                        db=db,
                    )
                    rows.append(
                        {
                            "query_id": query.id,
                            "mode": mode,
                            "milliseconds": (perf_counter() - started) * 1000,
                            "evidence_count": len(evidence),
                            **plan["retrieval_metrics"],
                        }
                    )
                print(f"Measured hot retrieval: {mode}", flush=True)
            after = process.cpu_times()
            result = {
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "logical_cpus": os.cpu_count(),
                    "physical_memory_bytes": psutil.virtual_memory().total,
                },
                "scope": "actual PostgreSQL/Qdrant hot retrieval; recorded real query "
                "embeddings; no LLM or mock provider timing",
                "concurrency": 1,
                "documents": 10,
                "chunks": 60,
                "rows": rows,
                "cold_warm_embedding": cold,
                "cache_hit_rate": sum(
                    bool(r["embedding_cache_hit"]) for r in rows if r["mode"] != "bm25"
                )
                / sum(r["mode"] != "bm25" for r in rows),
                "cpu_seconds": after.user + after.system - cpu.user - cpu.system,
                "peak_sampled_rss_bytes": max(process.memory_info().rss, peak[0]),
                "summary": {
                    mode: distribution([r["milliseconds"] for r in rows if r["mode"] == mode])
                    for mode in ["dense", "bm25", "hybrid", "hybrid_rerank"]
                },
            }
            Path("evaluation/results/performance.json").write_text(json.dumps(result, indent=2))
            print(
                json.dumps(
                    {
                        "summary": result["summary"],
                        "embedding": cold,
                        "cache_hit_rate": result["cache_hit_rate"],
                    }
                ),
                flush=True,
            )
    finally:
        stop.set()
        thread.join()
        with Session(engine) as db:
            user = db.get(User, owner)
            if user:
                db.delete(user)
                db.commit()
        resources.qdrant.delete_collection(collection)
        resources.qdrant.close()
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Service benchmark failed; provider/private details suppressed. "
            "Check disposable services."
        ) from None
