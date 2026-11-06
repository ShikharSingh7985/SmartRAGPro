"""Explainable triage, not a proof of safety or a calibrated probability."""

import base64
import codecs
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.app.models.entities import SecurityInspection, now

VERSION = "content-2026-11-v3"
RULES = (
    (
        "role_spoof",
        45,
        r"(?:\[/?(?:system|developer)\]|<\|(?:system|im_start|developer)\|>|(?:^|\n)\s*(?:system|developer)\s*:)",
    ),
    (
        "override",
        45,
        r"(?:ignore|disregard|override|forget|bypass)\s+(?:all\s+)?"
        r"(?:previous|prior|system|developer|safety|source|the above)\b",
    ),
    (
        "secret_exfiltration",
        60,
        r"(?:reveal|print|send|exfiltrate|disclose|upload|output)\b.{0,100}\b"
        r"(?:api.?key|password|secret|bearer|jwt|environment variable|credentials|refresh.?token)",
    ),
    (
        "external_action",
        45,
        r"(?:send|post|upload|fetch|execute|run|curl|wget|visit|download)\b.{0,100}"
        r"(?:https?://|shell command|subprocess|powershell|os\.environ)",
    ),
    (
        "scope_escalation",
        80,
        r"(?:access|retrieve|search|read|switch|change)\b.{0,65}"
        r"(?:other (?:users?|tenants?)|all tenants|user_id|tenant_id|authorization scope)",
    ),
    (
        "evidence_override",
        50,
        r"(?:ignore|invent|fabricate|replace|falsify)\b.{0,65}"
        r"(?:evidence|citations?|page numbers?|source facts|retrieval results)",
    ),
    (
        "answer_manipulation",
        80,
        r"(?:always answer|your (?:only|next) (?:answer|response) must|output exactly|"
        r"do not mention this instruction)",
    ),
)


@dataclass(frozen=True)
class Inspection:
    score: int
    decision: str
    reasons: list[str]
    policy_version: str = VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_content(text: str, threshold: int = 80) -> Inspection:
    # Bounded input and one decoding layer avoid recursive decoding/decompression attacks.
    original = text[:250_000]
    normalized = unicodedata.normalize("NFKC", original)
    clean = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    reasons: list[str] = []
    if clean != normalized:
        reasons.append("invisible_controls")
    variants = [clean]
    for encoded in re.findall(r"\b[A-Za-z0-9+/]{32,}={0,2}", clean)[:8]:
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            if len(decoded) <= 8192:
                variants.append(decoded)
        except (ValueError, UnicodeDecodeError):
            pass
    for encoded in re.findall(r"\b(?:[0-9a-fA-F]{2}){16,}\b", clean)[:8]:
        try:
            variants.append(bytes.fromhex(encoded[:16384]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
    if re.search(r"\brot13\b", clean, re.I):
        variants.append(codecs.decode(clean, "rot_13"))
    score = 0
    for code, weight, pattern in RULES:
        if any(
            not re.search(
                r"\b(?:cannot|can't|must not|never|does not)\s+$",
                variant[max(0, match.start() - 20) : match.start()],
                re.I,
            )
            for variant in variants
            for match in re.finditer(pattern, variant, re.I | re.S)
        ):
            reasons.append(code)
            score += weight
    if len(variants) > 1 and score:
        reasons.append("encoded_instruction")
        score += 40
    if "invisible_controls" in reasons and score:
        score += 40
    # Explicit quotations in educational text warrant review, not automatic quarantine.
    # This is a triage exception, never an authorization/capability exception.
    educational = bool(
        re.search(r"\b(?:prompt injection|security lesson|attack example)\b", clean, re.I)
    )
    outside_quotes = re.sub(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`', "", clean)
    quoted_only = (
        educational
        and outside_quotes != clean
        and not any(re.search(pattern, outside_quotes, re.I | re.S) for _, _, pattern in RULES)
    )
    if quoted_only and score:
        reasons.append("educational_quotation")
        score = min(score, threshold - 1)
    score = min(100, score)
    return Inspection(
        score, "block" if score >= threshold else "review" if score else "allow", reasons
    )


def record_inspection(
    db: Session, user_id: UUID, document_id: UUID, object_id: str, stage: str, result: Inspection
) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(SecurityInspection).values(
        id=uuid4(),
        created_at=now(),
        user_id=user_id,
        document_id=document_id,
        object_id=object_id[:128],
        stage=stage,
        policy_version=VERSION,
        decision=result.decision,
        score=result.score,
        reasons=result.reasons,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["document_id", "object_id", "stage", "policy_version"],
            set_={"decision": result.decision, "score": result.score, "reasons": result.reasons},
        )
    )


def inspection_text(value: Any) -> str:
    """Preserve literal quotations when inspecting structured data, without JSON escapes."""
    if isinstance(value, dict):
        return "\n".join(f"{key}: {inspection_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(inspection_text(item) for item in value)
    return str(value)


def safe_memory(value: Any, threshold: int = 80) -> bool:
    return inspect_content(inspection_text(value), threshold).decision != "block"


def unsafe_output(text: str, secrets: list[str]) -> bool:
    if any(secret and len(secret) >= 12 and secret in text for secret in secrets):
        return True
    if inspect_content(text).decision == "block":
        return True
    return bool(
        re.search(
            r"!\[[^\]]*\]\(\s*https?://|<\s*(?:script|iframe|img)\b|"
            r"(?:AIza[\w-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
            r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|"
            r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})|"
            r"(?:send|upload|post)\b.{0,80}(?:password|api.?key|bearer|jwt|secret)\b.{0,80}https?://",
            text,
            re.I | re.S,
        )
    )
