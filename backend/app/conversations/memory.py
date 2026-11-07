"""Bounded extractive memory with SQL provenance; never document evidence."""

import re
from typing import Any

import tiktoken
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.conversations.citations import strip_citations
from backend.app.core.config import Settings
from backend.app.models.entities import Conversation, ConversationSummary, Message
from backend.app.security.content import safe_memory

STOP_WORDS = {
    "what",
    "which",
    "when",
    "where",
    "that",
    "this",
    "those",
    "these",
    "with",
    "from",
    "about",
    "have",
    "does",
    "explain",
    "please",
    "earlier",
    "question",
    "answer",
}


def token_count(text: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))


def truncate(text: str, budget: int) -> str:
    encoding = tiktoken.get_encoding("cl100k_base")
    return encoding.decode(encoding.encode(text, disallowed_special=())[: max(0, budget)])


def scoped_messages(conversation: Conversation) -> Any:
    version = Message.turn_metadata["scope_version"].as_integer()
    return or_(
        version == conversation.scope_version,
        version.is_(None) if conversation.scope_version == 1 else version == -1,
    )


def reconstruct(
    db: Session, conversation: Conversation, question: str, settings: Settings
) -> dict[str, Any]:
    scoped = scoped_messages(conversation)
    base = select(Message).where(Message.conversation_id == conversation.id, scoped)
    recent = list(
        db.scalars(base.order_by(Message.position.desc()).limit(settings.chat_recent_messages))
    )
    recent.reverse()
    summary = db.get(ConversationSummary, conversation.id)
    if summary is None:
        summary = ConversationSummary(
            conversation_id=conversation.id, covered_through=0, version=0, content="", provenance=[]
        )
        db.add(summary)
    cutoff = recent[0].position - 1 if recent else 0
    older = list(
        db.scalars(
            base.where(Message.position > summary.covered_through, Message.position <= cutoff)
            .order_by(Message.position)
            .limit(settings.chat_summary_batch)
        )
    )
    if older:
        segments = list(summary.provenance)
        for message in older:
            if not safe_memory(message.content, settings.security_block_threshold):
                continue
            segments.append(
                {
                    "from": message.position,
                    "through": message.position,
                    "role": message.role,
                    "text": truncate(message.content, 48),
                }
            )

        def synopsis() -> str:
            return "\n".join(f"[{s['from']}] {s['role']}: {s['text']}" for s in segments)

        while segments and token_count(synopsis()) > settings.chat_summary_tokens:
            segments.pop(0)
        summary.content, summary.provenance = synopsis(), segments
        summary.covered_through = older[-1].position
        summary.version += 1
    # Relevant distant turns are retrieved from complete SQL history, not solely the synopsis.
    terms = list(dict.fromkeys(re.findall(r"[a-z0-9]{4,}", question.casefold())))
    terms = [term for term in terms if term not in STOP_WORDS][:12]
    recall: list[Message] = []
    if terms and cutoff > 0:
        candidates = base.where(Message.position <= cutoff)
        if db.get_bind().dialect.name == "postgresql":
            search = " | ".join(terms)
            candidates = candidates.where(
                func.to_tsvector("simple", Message.content).op("@@")(
                    func.to_tsquery("simple", search)
                )
            )
        else:
            candidates = candidates.where(
                or_(*[Message.content.ilike(f"%{term}%") for term in terms])
            )
        found = list(db.scalars(candidates.order_by(Message.position.desc()).limit(50)))
        found.sort(
            key=lambda message: sum(message.content.casefold().count(term) for term in terms),
            reverse=True,
        )
        recall = found[: settings.chat_recall_messages]
    if re.search(r"\b(first|initial|beginning)\b.*\b(question|asked|discussed)\b", question, re.I):
        first = db.scalar(base.where(Message.role == "user").order_by(Message.position).limit(1))
        if first:
            recall = [first, *recall][: settings.chat_recall_messages]
    history: list[dict[str, Any]] = []
    remaining = settings.chat_history_tokens
    for message in reversed(recent):
        if not safe_memory(message.content, settings.security_block_threshold):
            continue
        if remaining < 20:
            break
        content = truncate(message.content, min(remaining, 450))
        remaining -= token_count(content)
        history.append({"role": message.role, "content": content, "position": message.position})
    history.reverse()
    recalled = [
        {
            "role": message.role,
            "content": truncate(message.content, 160),
            "position": message.position,
        }
        for message in recall
        if safe_memory(message.content, settings.security_block_threshold)
    ]
    return {
        "history": history,
        "recalled": recalled,
        "summary": summary.content
        if safe_memory(summary.content, settings.security_block_threshold)
        else "",
        "summary_version": summary.version,
        "covered_through": summary.covered_through,
    }


def answer_methods(text: str, previous: list[str] | None = None) -> list[str]:
    lines = re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+(.+)", text)
    if lines:
        return [strip_citations(line).strip()[:600] for line in lines[:12]]
    # Models sometimes ignore list-format requests. Reconstruct only previously
    # named methods actually present in the latest prose, in their displayed order.
    prose = " ".join(re.sub(r"[*_`]", "", strip_citations(text)).split())
    mentions: dict[str, tuple[int, str]] = {}
    for method in (previous or [])[:12]:
        label = re.split(
            r":|\s[–—]\s|\s\((?=(?:which|that|uses?|reduces?|estimates?|ends?|"
            r"stops?|helps?|penalizes?|adds?|is|are|by)\b)",
            re.sub(r"[*_`]", "", method),
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        if not 4 <= len(label) <= 120:
            continue
        match = re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", prose, re.I)
        if match:
            mentions.setdefault(label.casefold(), (match.start(), label))
    return [label for _, label in sorted(mentions.values())]


DOCUMENT_REFERENCE = re.compile(
    r"\b(?:this|that|these|those|the|my|our|uploaded|selected)\s+"
    r"(?:(?:uploaded|selected)\s+)?(?:pdf|document|book|file|paper)s?\b",
    re.I,
)


def document_overview(question: str) -> bool:
    if re.search(r"\bchapter\s+(?:\d+|[ivx]+)\b", question, re.I):
        return False
    query = DOCUMENT_REFERENCE.sub("SOURCE", question).strip(" ?.!\\")
    return bool(
        re.search(
            r"\bwhat\b.{0,25}\bSOURCE\b.{0,12}\babout$|"
            r"\bsummari[sz]e\s+SOURCE\b|\b(?:summary|overview)\s+of\s+SOURCE\b|"
            r"\b(?:main|key)\s+(?:topics|points|themes|ideas|takeaways)\s+(?:of|in)\s+SOURCE\b|"
            r"\b(?:asking|tell\s+me|what)\s+about\s+SOURCE$|"
            r"\b(?:explain|describe)\s+SOURCE$",
            query,
            re.I,
        )
    )


def resolve(
    question: str,
    topic: str,
    references: dict[str, Any],
    history: list[dict[str, Any]],
    recalled: list[dict[str, Any]],
) -> dict[str, Any]:
    # Upgrade/recovery: existing pre-graph conversations already have durable SQL turns.
    if not topic:
        topic = next(
            (
                infer_topic(item["content"])
                for item in reversed(history)
                if item["role"] == "user" and infer_topic(item["content"])
            ),
            "",
        )
    if not references.get("methods"):
        previous = next(
            (item["content"] for item in reversed(history) if item["role"] == "assistant"), ""
        )
        references = {**references, "methods": answer_methods(previous)}
    # Demonstratives bound to an explicit source noun refer to the authorized
    # document scope, not necessarily to an earlier conversational entity.
    query = DOCUMENT_REFERENCE.sub("the selected document", question.strip())
    ordinal = re.search(
        r"\b(first|second|third|fourth|fifth|[1-5](?:st|nd|rd|th))\s+(?:method|technique|approach|option|item)",
        query,
        re.I,
    )
    followup_input = (
        re.sub(r"\bwhat\s+about\b", "", query, flags=re.I)
        if DOCUMENT_REFERENCE.search(question)
        else query
    )
    followup = bool(
        re.search(
            r"\b(it|its|they|them|their|those|these|that|this|former|latter)\b|what about|"
            r"\b(?:second|third|fourth)\s+method",
            followup_input,
            re.I,
        )
    )
    resolved: dict[str, str] = {}
    clarification = ""
    if re.search(r"\b(former|latter)\b", query, re.I):
        clarification = "Please name the option you mean so I can retrieve the right evidence."
    if ordinal:
        number = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}.get(
            ordinal[1].lower()
        )
        if number is None:
            number = int(ordinal[1][0]) - 1
        methods = references.get("methods", [])
        if number >= len(methods):
            clarification = "Which method do you mean? Please name it or specify an earlier answer."
        else:
            method = str(methods[number])
            query = query[: ordinal.start()] + method + query[ordinal.end() :]
            resolved[ordinal[0]] = method
            followup = True
    if followup:
        # Explicit distant-history references use matching user turns instead of the current topic.
        if recalled and re.search(
            r"\b(earlier|initial|first question|beginning)\b", question, re.I
        ):
            previous = next((item["content"] for item in recalled if item["role"] == "user"), "")
            if previous:
                topic = infer_topic(previous) or topic
        if not topic and not clarification:
            clarification = "What topic or earlier statement does your question refer to?"
        if topic:
            query = re.sub(r"\b(it|its|they|them|their)\b", topic, query, flags=re.I)
            query = f"{query}\nTopic: {topic}"
            resolved["topic"] = topic
            if re.search(r"\b(those|these)\s+(methods|techniques|approaches)\b", question, re.I):
                methods = references.get("methods", [])
                if methods:
                    query += "\nPreviously listed techniques: " + "; ".join(methods)[:1800]
                else:
                    clarification = (
                        "Which techniques would you like me to look up? Please name them."
                    )
    else:
        topic = infer_topic(query) or topic
    if (
        not followup
        and not DOCUMENT_REFERENCE.search(question)
        and re.match(r"\s*(how|why|which|can|what about)\b", query, re.I)
        and topic
    ):
        # Short elliptical questions (e.g. 'What about the disadvantages?') still need the topic.
        if (
            re.search(r"\b(disadvantages|advantages|limitations|example)\b", query, re.I)
            and len(query.split()) < 8
        ):
            query += f"\nTopic: {topic}"
    if document_overview(question):
        topic = "selected documents"
    return {
        "rewritten_question": query,
        "topic": topic,
        "resolved_references": resolved,
        "clarification": clarification,
        "is_followup": followup,
    }


def infer_topic(question: str) -> str:
    match = re.match(
        r"\s*(?:what (?:is|are)|explain|tell me about|describe)\s+(?:the\s+)?(.+?)[?.!]*$",
        question.strip(),
        re.I,
    )
    if not match:
        return ""
    topic = re.split(
        r"\s+(?:in chapter|in the (?:book|document)|from the|using the)\b", match[1], flags=re.I
    )[0]
    return topic.strip(" ?.!")[:250]
