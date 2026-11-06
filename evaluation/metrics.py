"""Chunk relevance metrics. Unanswerable queries are reported separately."""

import math
import random
import statistics


def retrieval_metrics(ranked: list[str], relevant: list[str]) -> dict[str, float]:
    ranked = list(dict.fromkeys(ranked))
    truth = set(relevant)
    result: dict[str, float] = {}
    for k in [1, 3, 5, 10]:
        hits = len(set(ranked[:k]) & truth)
        result[f"recall@{k}"] = hits / len(truth) if truth else 0.0
        result[f"precision@{k}"] = hits / k
        result[f"hit_rate@{k}"] = float(hits > 0)
        dcg = sum(
            1 / math.log2(rank + 2)
            for rank, identifier in enumerate(ranked[:k])
            if identifier in truth
        )
        ideal = sum(1 / math.log2(rank + 2) for rank in range(min(len(truth), k)))
        result[f"ndcg@{k}"] = dcg / ideal if ideal else 0.0
    result["mrr"] = next(
        (1 / rank for rank, identifier in enumerate(ranked, 1) if identifier in truth), 0.0
    )
    result["coverage"] = len(set(ranked) & truth) / len(truth) if truth else 0.0
    return result


def interval(values: list[float], seed: int = 781) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(1000))
    return [means[24], means[974]] if values else [0.0, 0.0]


def distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None}
    ordered = sorted(values)

    def percentile(p):
        return ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)]

    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "p50": percentile(0.5),
        "p95": percentile(0.95) if len(values) >= 20 else None,
        "p99": percentile(0.99) if len(values) >= 100 else None,
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }
