"""Shared production/evaluation ranking primitives. No provider mocks."""

import math
import re
from collections import Counter
from typing import Any

from backend.app.core.telemetry import observed

STOP = frozenset(
    (
        "a an the is are was were what which how why when where who of to in on for "
        "and or with from does do it those these about explain please can"
    ).split()
)


def terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[^\W_]+(?:[-.][^\W_]+)*", text.casefold())
        if word not in STOP and len(word) <= 80
    ]


def bm25_scores(query: str, texts: list[str]) -> list[float]:
    """Reference Okapi BM25 (k1=1.5,b=.75), statistics from scoped corpus only."""
    frequencies = [Counter(terms(text)) for text in texts]
    lengths = [sum(freq.values()) for freq in frequencies]
    count = len(texts)
    average = sum(lengths) / max(count, 1) or 1
    scores = [0.0] * count
    for term in set(terms(query)):
        df = sum(term in freq for freq in frequencies)
        idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
        for index, freq in enumerate(frequencies):
            tf = freq[term]
            scores[index] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * lengths[index] / average))
    return scores


def rrf(lexical: list[str], dense: list[str], weight: float = 0.5, k: int = 60) -> list[str]:
    """Weight is lexical share; dense share = 1-weight. Fuse ranks, not raw scores."""
    scores: dict[str, float] = {}
    for sequence, share in [(lexical, weight), (dense, 1 - weight)]:
        if share == 0:
            continue
        for rank, identifier in enumerate(dict.fromkeys(sequence), 1):
            scores[identifier] = scores.get(identifier, 0) + share / (k + rank)
    return sorted(scores, key=lambda identifier: (-scores[identifier], identifier))


@observed("retrieval.rerank")
def rerank(query: str, candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Documented non-neural alternative: query coverage, bigram proximity, fused prior.

    Lexicographic ranking avoids mixing incomparable cosine/BM25 values. No model load,
    no network, bounded to limit candidates and 8000 characters per candidate.
    """
    query_terms = terms(query)[:80]
    unique = set(query_terms)
    pairs = set(zip(query_terms, query_terms[1:], strict=False))

    def key(item: tuple[int, dict[str, Any]]) -> tuple[float, float, int]:
        position, candidate = item
        words = terms(str(candidate["text"])[:8000])
        coverage = len(unique.intersection(words)) / max(1, len(unique))
        proximity = len(pairs.intersection(zip(words, words[1:], strict=False))) / max(
            1, len(pairs)
        )
        return (-coverage, -proximity, position)

    bounded = candidates[:limit]
    return [item for _, item in sorted(enumerate(bounded), key=key)] + candidates[limit:]


def deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[tuple[str, int], list[set[str]]] = {}
    for candidate in candidates:
        words = set(terms(str(candidate["text"])))
        key = (str(candidate.get("document_id")), int(candidate.get("page", 0)))
        if any(len(words & old) / max(1, len(words | old)) >= 0.92 for old in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append(words)
        result.append(candidate)
    return result
