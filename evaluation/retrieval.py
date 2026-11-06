"""Comparable TF-IDF/BM25/dense/RRF/rerank experiments; real Google embeddings."""

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path
from time import perf_counter

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.app.conversations.memory import infer_topic, resolve
from backend.app.core.config import get_settings
from backend.app.rag.ranking import bm25_scores, deduplicate, rerank, rrf, terms
from backend.app.services.resources import GoogleGenerativeAIEmbeddings
from evaluation.dataset import load
from evaluation.metrics import distribution, interval, retrieval_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evaluation/data/synthetic.json")
    parser.add_argument("--output", default="evaluation/results")
    parser.add_argument(
        "--qdrant", help="Real Qdrant server; otherwise actual in-process Qdrant engine"
    )
    args = parser.parse_args()
    dataset = load(args.dataset)
    settings = get_settings()
    if settings.embedding_provider != "google":
        raise SystemExit(
            "This live experiment uses Google embeddings; configure that provider explicitly"
        )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path("evaluation/.cache")
    cache.mkdir(exist_ok=True)
    signature = hashlib.sha256(
        (
            dataset.fingerprint() + settings.embedding_model + str(settings.embedding_dimensions)
        ).encode()
    ).hexdigest()
    embedding_file = cache / (signature + ".json")
    queries = []
    rewrites = []
    for query in dataset.queries:
        started = perf_counter()
        topic = infer_topic(query.context[-1]["content"]) if query.context else ""
        resolved = resolve(query.text, topic, {}, query.context, [])
        queries.append(resolved["rewritten_question"])
        rewrites.append(
            {
                "query_id": query.id,
                "milliseconds": (perf_counter() - started) * 1000,
                "clarification": bool(resolved["clarification"]),
            }
        )
    stored = json.loads(embedding_file.read_text()) if embedding_file.exists() else {}
    cache_hit = len(stored.get("queries", [])) == len(queries)

    def call_provider(function):
        for attempt in range(6):
            try:
                return function()
            except Exception as exc:
                cause = exc.__cause__ or exc
                code = getattr(cause, "code", None)
                if code not in {429, 503} or attempt == 5:
                    raise RuntimeError(
                        "Live embedding request failed; partial progress retained"
                    ) from None
                print(f"Provider HTTP {code}; bounded retry {attempt + 1}/5", flush=True)
                time.sleep(15)

    if not cache_hit:
        if not settings.gemini_api_key.get_secret_value():
            raise SystemExit(
                "Configure GEMINI_API_KEY locally; dense benchmarks never substitute mocks"
            )
        provider = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.gemini_api_key,
            output_dimensionality=settings.embedding_dimensions,
            vertexai=False,
            client_args={"timeout": 60},
        )
        if not stored:
            started = perf_counter()
            vectors = call_provider(
                lambda: provider.embed_documents(
                    [chunk.text for chunk in dataset.chunks], batch_size=16
                )
            )
            stored = {
                "vectors": vectors,
                "queries": [],
                "document_ms": (perf_counter() - started) * 1000,
                "query_ms": [],
                "model": settings.embedding_model,
                "dimensions": settings.embedding_dimensions,
            }
            embedding_file.write_text(json.dumps(stored))
        for index in range(len(stored["queries"]), len(queries)):
            query = queries[index]
            started = perf_counter()
            stored["queries"].append(call_provider(lambda text=query: provider.embed_query(text)))
            stored["query_ms"].append((perf_counter() - started) * 1000)
            embedding_file.write_text(json.dumps(stored))
            if index % 20 == 0:
                print(f"Embedded {index + 1}/{len(queries)} real query vectors", flush=True)
            time.sleep(0.7)
    client = QdrantClient(url=args.qdrant) if args.qdrant else QdrantClient(":memory:")
    collection = "smartrag_eval_" + signature[:12]
    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.create_collection(
        collection,
        vectors_config=qm.VectorParams(
            size=settings.embedding_dimensions, distance=qm.Distance.COSINE
        ),
    )
    client.upsert(
        collection,
        points=[
            qm.PointStruct(
                id=index + 1,
                vector=vector,
                payload={"document_id": chunk.document_id, "user_id": "synthetic-evaluation"},
            )
            for index, (chunk, vector) in enumerate(
                zip(dataset.chunks, stored["vectors"], strict=True)
            )
        ],
        wait=True,
    )
    rows, rankings, stages = [], {}, []
    try:
        for index, query in enumerate(dataset.queries):
            corpus = [chunk for chunk in dataset.chunks if chunk.document_id in query.document_ids]
            texts, ids = [c.text for c in corpus], [c.id for c in corpus]
            started = perf_counter()
            tfidf = TfidfVectorizer(tokenizer=terms, token_pattern=None)
            matrix = tfidf.fit_transform(texts)
            tfidf_build = (perf_counter() - started) * 1000
            started = perf_counter()
            scores = (matrix @ tfidf.transform([queries[index]]).T).toarray().ravel()
            lexical_tfidf = [ids[i] for i in np.argsort(-scores, kind="stable") if scores[i] > 0]
            tfidf_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            scores = bm25_scores(queries[index], texts)
            bm25 = [
                ids[i]
                for i in sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
                if scores[i] > 0
            ]
            bm25_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            filt = qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="user_id", match=qm.MatchValue(value="synthetic-evaluation")
                    ),
                    qm.FieldCondition(key="document_id", match=qm.MatchAny(any=query.document_ids)),
                ]
            )
            points = client.query_points(
                collection,
                query=stored["queries"][index],
                query_filter=filt,
                limit=24,
                score_threshold=0.25,
            ).points
            dense = [dataset.chunks[int(point.id) - 1].id for point in points]
            dense_ms = (perf_counter() - started) * 1000
            by_id = {chunk.id: chunk.model_dump() for chunk in corpus}
            variants = {"tfidf": lexical_tfidf, "bm25": bm25, "dense": dense}
            for weight in [0.0, 0.3, 0.5, 0.7, 1.0]:
                started = perf_counter()
                fused = rrf(bm25[:24], dense, weight)
                fusion_ms = (perf_counter() - started) * 1000
                name = f"rrf_{weight:.1f}"
                variants[name] = fused
                started = perf_counter()
                ranked = rerank(queries[index], [by_id[key] for key in fused], 24)
                rerank_ms = (perf_counter() - started) * 1000
                variants[name + "_rerank"] = [item["id"] for item in ranked]
                variants[name + "_dedup"] = [
                    item["id"] for item in deduplicate([by_id[key] for key in fused])
                ]
                stages.append(
                    {
                        "query_id": query.id,
                        "variant": name,
                        "fusion_ms": fusion_ms,
                        "rerank_ms": rerank_ms,
                    }
                )
            # Ablate context reconstruction, using the identical dense corpus and model.
            if query.category == "followup":
                # Bare-query lexical ablation avoids an extra provider call.
                raw = bm25_scores(query.text, texts)
                variants["bm25_no_rewrite"] = [
                    ids[i] for i in sorted(range(len(ids)), key=lambda i: -raw[i]) if raw[i] > 0
                ]
            for name, ranked in variants.items():
                rankings[f"{query.id}:{name}"] = ranked
                metric = retrieval_metrics(ranked[:10], query.relevant_ids)
                rows.append(
                    {
                        "query_id": query.id,
                        "variant": name,
                        "split": query.split,
                        "category": query.category,
                        "answerable": query.answerable,
                        **metric,
                        "tfidf_ms": tfidf_ms,
                        "tfidf_build_ms": tfidf_build,
                        "lexical_ms": bm25_ms,
                        "dense_ms": dense_ms,
                    }
                )
        validation = [
            row
            for row in rows
            if row["split"] == "validation"
            and row["answerable"]
            and row["variant"].startswith("rrf_")
            and not row["variant"].endswith("_dedup")
        ]
        variants = sorted({row["variant"] for row in validation})
        selected = max(
            variants,
            key=lambda name: (
                statistics.mean(r["recall@5"] for r in validation if r["variant"] == name),
                statistics.mean(r["mrr"] for r in validation if r["variant"] == name),
                -len(name),
            ),
        )
        aggregates = []
        for split in ["validation", "test"]:
            for name in sorted({row["variant"] for row in rows}):
                subset = [
                    r
                    for r in rows
                    if r["split"] == split and r["variant"] == name and r["answerable"]
                ]
                if not subset:
                    continue
                aggregates.append(
                    {
                        "variant": name,
                        "split": split,
                        "n": len(subset),
                        **{
                            key: statistics.mean(r[key] for r in subset)
                            for key in retrieval_metrics([], [])
                        },
                        "recall5_ci95": interval([r["recall@5"] for r in subset]),
                    }
                )
        result = {
            "parameters": {
                "candidate_limit": 24,
                "cosine_threshold": 0.25,
                "rrf_k": 60,
                "bm25_k1": 1.5,
                "bm25_b": 0.75,
                "tfidf_norm": "l2",
                "idf_smoothing": True,
                "reranker": "bounded term coverage, bigram overlap, prior rank",
                "rerank_max_characters": 8000,
                "relevance_unit": "authored page-chunk",
            },
            "dataset_sha256": dataset.fingerprint(),
            "dataset_version": dataset.version,
            "label_status": "synthetic, not independently reviewed",
            "selected_on_validation": selected,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "logical_cpus": os.cpu_count(),
            },
            "corpus": {
                "documents": len({c.document_id for c in dataset.chunks}),
                "chunks": len(dataset.chunks),
                "queries": len(dataset.queries),
            },
            "embedding": {
                "provider": "google",
                "index_version": settings.embedding_version,
                "model": stored["model"],
                "dimensions": stored["dimensions"],
                "cache_hit": cache_hit,
                "document_ms": stored["document_ms"],
                "query_latency_ms": distribution(stored["query_ms"]),
            },
            "qdrant": "server" if args.qdrant else "in-process actual engine",
            "aggregates": aggregates,
            "rewrites": rewrites,
            "stages": stages,
            "rankings": rankings,
            "per_query_csv": "retrieval.csv",
        }
        (output / "retrieval.json").write_text(json.dumps(result, indent=2))
        with (output / "retrieval.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(
            json.dumps(
                {
                    "selected": selected,
                    "test": [
                        r
                        for r in aggregates
                        if r["split"] == "test"
                        and r["variant"] in {"tfidf", "bm25", "dense", selected}
                    ],
                }
            ),
            flush=True,
        )
    finally:
        client.delete_collection(collection)
        client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Benchmark failed; check service configuration/quota. "
            "Provider details suppressed; resumable embeddings retained."
        ) from None
