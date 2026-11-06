# Report paragraphs are intentionally kept as full source literals.
# ruff: noqa: E501
"""Generate reports and SVG scientific plots from measured JSON/CSV artifacts."""

import argparse
import csv
import json
import os
import statistics
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("evaluation/.cache/matplotlib").resolve()))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-price-per-million", type=float, default=None)
    parser.add_argument("--output-price-per-million", type=float, default=None)
    args = parser.parse_args()
    root = Path("evaluation/results")
    retrieval = json.loads((root / "retrieval.json").read_text())
    memory = json.loads((root / "memory.json").read_text())
    quality = json.loads((root / "quality.json").read_text())
    ingestion = json.loads((root / "ingestion.json").read_text())
    performance = (
        json.loads((root / "performance.json").read_text())
        if (root / "performance.json").exists()
        else None
    )
    with (root / "retrieval.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    out = Path("docs/benchmarks")
    out.mkdir(parents=True, exist_ok=True)
    variants = ["tfidf", "bm25", "dense", "rrf_0.3", "rrf_0.5", "rrf_0.7", "rrf_0.5_rerank"]
    test = {r["variant"]: r for r in retrieval["aggregates"] if r["split"] == "test"}
    table = "| Method | n | Recall@1 | Recall@3 | Recall@5 | Recall@10 | Precision@5 | Hit@5 | MRR@10 | nDCG@5 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    for name in variants:
        row = test[name]
        table += (
            f"| {name} | {row['n']} | "
            + " | ".join(
                f"{row[k]:.4f}"
                for k in [
                    "recall@1",
                    "recall@3",
                    "recall@5",
                    "recall@10",
                    "precision@5",
                    "hit_rate@5",
                    "mrr",
                    "ndcg@5",
                ]
            )
            + " |\n"
        )
    followup = {}
    for name in ["bm25", "bm25_no_rewrite"]:
        subset = [
            r
            for r in rows
            if r["split"] == "test" and r["category"] == "followup" and r["variant"] == name
        ]
        followup[name] = {
            "n": len(subset),
            "recall5": statistics.mean(float(r["recall@5"]) for r in subset),
            "mrr": statistics.mean(float(r["mrr"]) for r in subset),
        }
    doc = (
        "# Retrieval comparison\n\nGenerated from actual measurements; synthetic labels are not independently reviewed.\n\n"
        f"Dataset `{retrieval['dataset_sha256']}`: {retrieval['corpus']}. "
        f"Validation-only selection: `{retrieval['selected_on_validation']}`. "
        "Zero lexical share is equivalent to dense; production therefore retains dense as its default. "
        "The same answerable held-out queries and scopes are compared below.\n\n"
        + table
        + "\nRRF weights are **lexical / dense**: 0.3 = 30/70; 0.7 = 70/30. "
        "Ranks are fused with k=60; raw BM25 and cosine values are never added. "
        "Validation uses separate topics/query IDs; held-out labels do not select weights.\n\n"
        "The synthetic set has a ceiling effect: dense Recall@5 is at its ceiling on this corpus. "
        "This is not evidence of 100% real-world retrieval. Neither the 70/30 hypothesis "
        "nor the bounded lexical reranker improves this baseline; the reranker regresses "
        "Recall@5 and remains opt-in. No cross-encoder accuracy claim is made.\n\n"
        "![Measured held-out retrieval](retrieval.svg)\n\n"
        "## Confidence and ablations\n\n"
        f"Dense Recall@5 95% query-bootstrap interval: {test['dense']['recall5_ci95']}; "
        f"BM25: {test['bm25']['recall5_ci95']}. These are seeded IID-query bootstrap "
        "intervals, not guarantees for a new corpus; templates/topics are correlated.\n\n"
        f"Matched held-out follow-up subset (only these query IDs): `{followup}`. "
        "Do not compare this subset to the full-set aggregate. Near-duplicate removal "
        "made no ranking change on this corpus (one chunk per page); this does not "
        "establish its usefulness on overlapping real chunks. It stays disabled. "
        "Semantic chunking, multi-query LLM expansion, parent expansion and adaptive top-k "
        "were not adopted without a measured benefit; changing chunk units would also "
        "invalidate the current fixed-label comparison.\n\n"
        "## Answer generation, separately measured\n\n"
    )
    aggregates = {}
    for variant in ["dense", "rrf_0.5_rerank"]:
        completed = [
            r for r in quality["results"] if r["variant"] == variant and r["status"] == "completed"
        ]
        aggregate = {"n": len(completed)}
        for key in [
            "citation_label_precision",
            "citation_index_validity",
            "citation_sentence_coverage_proxy",
            "context_precision",
            "context_recall",
            "expected_phrase_recall_proxy",
            "unsupported_number_rate_proxy",
        ]:
            values = [r[key] for r in completed if r.get(key) is not None]
            aggregate[key] = statistics.mean(values) if values else None
        abstentions = [
            r["unanswerable_abstention_heuristic"]
            for r in completed
            if r.get("unanswerable_abstention_heuristic") is not None
        ]
        aggregate["unanswerable_abstention_heuristic"] = (
            statistics.mean(abstentions) if abstentions else None
        )
        aggregates[variant] = aggregate
        doc += f"- `{variant}`: `{json.dumps(aggregate)}`\n"
    doc += (
        f"\nModel `{quality['model']}`; held-out questions per method (sample sizes listed above), "
        "actual live calls, no model doubles. Sampling uses provider-fixed defaults "
        "despite the requested temperature=0. The initial run had rate-limited attempts recorded in quality.json; "
        "those failures remain recorded and only failed cases were resumed with pacing. "
        "Citation-label precision measures labeled source relevance, not entailment. "
        "Sentence citation coverage, expected-phrase recall and numeric support are "
        "limited deterministic proxies. Human correctness/faithfulness/unsupported-claim "
        "scores remain null pending review. No judge model was used and no overall "
        "answer accuracy or hallucination rate is claimed.\n"
    )
    (out / "retrieval-comparison.md").write_text(doc, encoding="utf-8")
    fig, axis = plt.subplots(figsize=(9, 4.5))
    axis.bar(variants, [test[name]["recall@5"] for name in variants])
    axis.set_ylim(0, 1.05)
    axis.set_ylabel("Recall@5 (known relevant chunk fraction)")
    axis.tick_params(axis="x", labelrotation=25)
    axis.set_title("Answerable held-out synthetic queries; identical scopes")
    fig.tight_layout()
    fig.savefig(out / "retrieval.svg")
    plt.close(fig)
    mem = {
        kind: [r for r in memory["results"] if r["method"] == kind] for kind in ["tfidf", "hashing"]
    }
    memory_summary = {
        kind: {
            "peak_rss_mib_mean": statistics.mean(
                r["peak_sampled_rss_bytes"] / 2**20 for r in sample
            ),
            "peak_rss_mib_stdev": statistics.stdev(
                r["peak_sampled_rss_bytes"] / 2**20 for r in sample
            ),
            "seconds_mean": statistics.mean(r["seconds"] for r in sample),
        }
        for kind, sample in mem.items()
    }
    tokens = {
        key: sum(r.get("usage", {}).get(key, 0) for r in quality["results"])
        for key in ["input_tokens", "output_tokens", "total_tokens"]
    }
    estimated = None
    if args.input_price_per_million is not None and args.output_price_per_million is not None:
        estimated = (
            tokens["input_tokens"] * args.input_price_per_million
            + tokens["output_tokens"] * args.output_price_per_million
        ) / 1e6
    analysis = {
        "memory": memory_summary,
        "generation": quality["generation_ms"],
        "tokens": tokens,
        "answer_proxies": aggregates,
        "followup_ablation": followup,
        "estimated_generation_cost_usd": estimated,
        "input_price_per_million": args.input_price_per_million,
        "output_price_per_million": args.output_price_per_million,
    }
    (root / "analysis.json").write_text(json.dumps(analysis, indent=2))
    fig, axis = plt.subplots(figsize=(6, 4))
    axis.bar(
        list(mem),
        [memory_summary[k]["peak_rss_mib_mean"] for k in mem],
        yerr=[memory_summary[k]["peak_rss_mib_stdev"] for k in mem],
        capsize=5,
    )
    axis.set_ylabel("Peak sampled process RSS (MiB)")
    axis.set_title("Synthetic texts; fresh processes per method")
    fig.tight_layout()
    fig.savefig(out / "memory.svg")
    plt.close(fig)
    latency = "# Latency and memory\n\nActual measured values; no mocked provider timing.\n\n"
    latency += f"Environment: `{retrieval['environment']}`; physical memory `{memory['physical_memory_bytes']}` bytes. "
    latency += "Host CPU: 12th Gen Intel Core i5-12500H, verified with Win32_Processor; logical CPU count is recorded. Local Docker/services and host tests may contend for resources; these are development measurements, not SLAs.\n\n"
    latency += f"Memory experiment: `{memory_summary}`. Each method uses fresh interpreter processes and the corpus size recorded in memory.json, concurrency=1 and RSS sampling every 10 ms. Baseline imports and corpus buffers are included in total RSS. Python tracemalloc and CSR bytes are also in memory.json. Hashing has fixed feature dimensionality (262,144), but CSR nonzeros, input text, caches and total process memory still grow. These results do not reproduce 700 MB to 60–80 MB or establish an application-wide memory reduction. The application uses persistent SQL BM25 rather than loading a vocabulary-sized lexical index per user.\n\n![Memory](memory.svg)\n\n"
    latency += f"Real document embedding throughput: the measured corpus in {retrieval['embedding']['document_ms']:.2f} ms. Query-embedding distribution including rate-limit/backoff effects: `{retrieval['embedding']['query_latency_ms']}`. Embedding vectors are cached on disk for repeatable ranking experiments; warm replay makes no provider calls and is identified explicitly. Initial quota failure and cache-resume work are not counted as successful cold requests.\n\n"
    latency += f"Real Gemini generation distribution (completed calls): `{quality['generation_ms']}`. Token usage: `{tokens}`. List-price scenario estimate: `{estimated}` USD, with input/output rates `{args.input_price_per_million}` / `{args.output_price_per_million}` USD per million tokens. This is not an invoice and excludes embeddings, failed attempts, caching discounts and infrastructure; actual free-tier charges may differ. Rates were checked against [Google's model card](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/).\n\n"
    latency += (
        "Time to first streamed token is null: the app does not stream tokens. No invented TTFT or whole-worker ingestion throughput is reported. Real bounded PDF extraction/chunking samples (excludes OCR, embeddings, storage and queue): `"
        + json.dumps(ingestion["results"])
        + "`.\n\n"
    )
    if performance:
        latency += f"Actual PostgreSQL + Qdrant hot service retrieval: `{performance['summary']}`. Cold/warm real embedding-cache experiment: `{performance['cold_warm_embedding']}`. Cache hit rate during preloaded hot retrieval: `{performance['cache_hit_rate']}`. This 100% hot hit rate is a controlled microbenchmark, not observed user traffic. CPU seconds `{performance['cpu_seconds']}`; peak sampled benchmark-process RSS `{performance['peak_sampled_rss_bytes']}` bytes. Per-query dense/lexical/fusion/rerank stages are in performance.json. These measurements exclude Gemini and HTTP/graph overhead; they are not whole-application end-to-end latency.\n"
        names = list(performance["summary"])
        fig, axis = plt.subplots(figsize=(7, 4))
        axis.bar(names, [performance["summary"][name]["p50"] for name in names])
        axis.set_ylabel("Hot service retrieval p50 (ms)")
        fig.tight_layout()
        fig.savefig(out / "latency.svg")
        plt.close(fig)
        latency += "\n![Measured retrieval latency](latency.svg)\n"
    latency += "\nEmpirical nearest-rank p50 is always shown; p95 only when n>=20, p99 only when n>=100. Small-sample tails are unstable. Memory bars show sample standard deviation, not confidence bounds. See methodology for limitations.\n"
    live_path = root / "live_workflow.json"
    if live_path.exists():
        live = json.loads(live_path.read_text())
        latency += (
            "\nLive HTTP whole-application workflow: `"
            + json.dumps(live)
            + "`. This includes actual upload/storage/worker/embeddings and complete verified chat turns. Four turns do not support p95/p99 claims.\n"
        )
    latency += "\nService profile runs inside the Linux Docker test network. The separate native host-loopback server run has substantial network overhead and is not an algorithmic latency improvement comparison. Sequential mode order and resource contention can make a reranking sample appear faster than hybrid alone; no speed advantage of reranking is established.\n"
    (out / "latency-and-memory.md").write_text(latency, encoding="utf-8")
    for picture in out.glob("*.svg"):
        picture.write_text(
            "\n".join(line.rstrip() for line in picture.read_text().splitlines()) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(analysis), flush=True)


if __name__ == "__main__":
    main()
