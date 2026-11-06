import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import tiktoken

from backend.app.core.config import Settings


@dataclass
class Element:
    page: int
    kind: str
    text: str
    identifier: str
    method: str
    heading: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    asset_id: str | None = None
    model_derived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeChunk:
    page: int
    text: str
    chunk_id: str
    parent_id: str
    page_end: int
    metadata: dict[str, Any]


def embedding_fingerprint(settings: Settings) -> str:
    model = (
        settings.local_embedding_model
        if settings.embedding_provider == "local"
        else settings.embedding_model
    )
    value = (
        f"{settings.embedding_provider}:{model}:"
        f"{settings.embedding_dimensions}:{settings.embedding_version}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


def structured_chunks(elements: list[Element], settings: Settings) -> list[KnowledgeChunk]:
    """Keep tables as header-repeated row groups; retain bounded parent context and provenance."""
    encoder = tiktoken.get_encoding("cl100k_base")
    chunks: list[KnowledgeChunk] = []
    for element in elements:
        parent = hashlib.sha256(json.dumps(element.to_dict(), sort_keys=True).encode()).hexdigest()
        segments: list[str] = []
        if element.kind == "table":
            headers = element.data.get("headers", [])
            rows = element.data.get("rows", [])
            prefix = f"{element.text}\nHeaders: {json.dumps(headers, ensure_ascii=False)}\n"
            group = prefix
            for row in rows:
                line = "Row: " + json.dumps(row, ensure_ascii=False) + "\n"
                if len(encoder.encode(group + line)) > settings.chunk_tokens and group != prefix:
                    segments.append(group)
                    group = prefix
                group += line
            if group != prefix:
                segments.append(group)
        else:
            tokens = encoder.encode(element.text)
            stride = settings.chunk_tokens - settings.chunk_overlap_tokens
            segments = [
                encoder.decode(tokens[start : start + settings.chunk_tokens])
                for start in range(0, len(tokens), stride)
            ]
        for index, text in enumerate(segments):
            if not text.strip():
                continue
            # A single table row may be wider than the budget: preserve its integrity and flag it.
            metadata = {
                "content_type": element.kind,
                "section_heading": element.heading,
                "element_id": element.identifier,
                "extraction_method": element.method,
                "asset_id": element.asset_id,
                "model_derived": element.model_derived,
                "oversized_row": len(encoder.encode(text)) > settings.chunk_tokens,
                "parent_context": element.text[:1800],
            }
            identifier = hashlib.sha256(f"{parent}:{index}:{text}".encode()).hexdigest()
            chunks.append(
                KnowledgeChunk(element.page, text, identifier, parent, element.page, metadata)
            )
    return chunks
