"""A deterministic LangGraph with finite context and authoritative SQL history."""

import logging
import re
from time import perf_counter
from typing import Any, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.conversations.citations import normalize_citations
from backend.app.conversations.evidence import retrieve, select_evidence
from backend.app.conversations.memory import (
    answer_methods,
    reconstruct,
    resolve,
    token_count,
    truncate,
)
from backend.app.conversations.rewriting import rewrite_followup
from backend.app.core.telemetry import EVENTS, VALUES, observed
from backend.app.models.entities import Conversation, Document, Message
from backend.app.schemas.api import Question
from backend.app.security.content import inspect_content, safe_memory, unsafe_output
from backend.app.services.resources import ABSTENTION, Resources

logger = logging.getLogger(__name__)


class ConversationState(TypedDict, total=False):
    user_id: str
    conversation_id: str
    document_ids: list[str]
    scope_version: int
    current_message: str
    history: list[dict[str, Any]]
    recalled: list[dict[str, Any]]
    summary: str
    summary_version: int
    covered_through: int
    topic: str
    references: dict[str, Any]
    resolved_references: dict[str, Any]
    rewritten_question: str
    clarification: str
    is_followup: bool
    plan: dict[str, Any]
    evidence: list[dict[str, Any]]
    generation: str
    citations: list[dict[str, Any]]
    errors: list[str]
    budgets: dict[str, int]
    timings_ms: dict[str, float]
    response_id: str


def build_graph(
    db: Session,
    resources: Resources,
    conversation: Conversation,
    documents: list[Document],
    question: Question,
    saver: Any,
) -> Any:
    settings = resources.settings
    timings: dict[str, float] = {}

    def validate(state: ConversationState) -> dict[str, Any]:
        if state["user_id"] != str(conversation.user_id):
            raise HTTPException(404, "Conversation not found")
        return {"errors": [], "clarification": "", "evidence": [], "citations": []}

    def memory(state: ConversationState) -> dict[str, Any]:
        start = perf_counter()
        result = reconstruct(db, conversation, state["current_message"], settings)
        timings["memory"] = (perf_counter() - start) * 1000
        return result

    def references(state: ConversationState) -> dict[str, Any]:
        start = perf_counter()
        if (
            inspect_content(state["current_message"], settings.security_block_threshold).decision
            == "block"
        ):
            return {
                "clarification": "I cannot follow instructions to bypass security "
                "or disclose private credentials.",
                "rewritten_question": "",
                "is_followup": False,
                "resolved_references": {},
            }
        result = resolve(
            state["current_message"],
            state["topic"],
            state["references"],
            state["history"],
            state["recalled"],
        )
        timings["resolution"] = (perf_counter() - start) * 1000
        return result

    def rewrite(state: ConversationState) -> dict[str, Any]:
        start = perf_counter()
        query = truncate(state["rewritten_question"], 1800)
        topic, clarification = state["topic"], state["clarification"]
        if settings.chat_llm_rewrite and state["is_followup"] and not clarification:
            import json

            context = truncate(
                json.dumps(
                    {
                        "history": state["history"],
                        "recalled": state["recalled"],
                        "summary": state["summary"],
                        "references": state["references"],
                    }
                ),
                settings.chat_history_tokens,
            )
            result = rewrite_followup(state["current_message"], context, settings)
            query, topic, clarification = result.query, result.topic, result.clarification
        if not safe_memory(query + topic, settings.security_block_threshold):
            query, topic = "", ""
            clarification = "Please rephrase your question about the selected documents."
        timings["rewrite"] = (perf_counter() - start) * 1000
        if settings.environment == "development" and settings.chat_trace_queries:
            logger.debug("Query original=%r rewritten=%r", state["current_message"], query)
        return {"rewritten_question": query, "topic": topic, "clarification": clarification}

    def plan(state: ConversationState) -> dict[str, Any]:
        query = state["current_message"]
        chapter = re.search(r"\bchapter\s+(\d+|[ivx]+)\b", query, re.I)
        compare = bool(
            re.search(r"\b(compare|contradict|disagree|across|both books)\b", query, re.I)
        )
        clarification = state["clarification"]
        named = [doc for doc in documents if doc.filename.casefold() in query.casefold()]
        filenames = re.findall(r"[\w.-]+\.pdf\b", query, re.I)
        if any(
            name.casefold() not in {d.filename.casefold() for d in documents} for name in filenames
        ):
            clarification = (
                "Please select the referenced PDF in this conversation's document scope."
            )
        if compare and len(documents) < 2:
            clarification = "Select both documents before asking for a comparison."
        if not documents:
            clarification = "No selected source is ready. Select an available document to continue."
        return {
            "plan": {
                "chapter": chapter[1] if chapter else None,
                "compare": compare,
                "document_ids": [str(d.id) for d in named]
                if named and not compare
                else state["document_ids"],
            },
            "clarification": clarification,
        }

    def retrieval(state: ConversationState) -> dict[str, Any]:
        start = perf_counter()
        chosen = [d for d in documents if str(d.id) in state["plan"]["document_ids"]]
        result = retrieve(
            resources,
            conversation.user_id,
            chosen,
            state["rewritten_question"],
            state["plan"],
            db=db,
        )
        timings["retrieval"] = (perf_counter() - start) * 1000
        return {"evidence": result, "plan": state["plan"]}

    def selection(state: ConversationState) -> dict[str, Any]:
        available = (
            settings.chat_context_tokens
            - token_count(state["current_message"])
            - token_count(state["rewritten_question"])
            - 700
        )
        if available < 300:
            raise HTTPException(422, "Question exceeds the configured context budget; shorten it")
        selected = select_evidence(
            state["evidence"], min(settings.chat_evidence_tokens, available // 2)
        )
        if state["plan"]["compare"] and len({e["document_id"] for e in selected}) < 2:
            return {"evidence": [], "errors": ["insufficient_comparison_evidence"]}
        return {"evidence": selected}

    def generate(state: ConversationState) -> dict[str, Any]:
        if state["clarification"]:
            return {"generation": state["clarification"]}
        if not state["evidence"]:
            return {
                "generation": "I don't know based on the selected documents. "
                "No sufficient evidence was found."
            }
        context = "\n\n".join(
            f"[{e['source']}] UNTRUSTED DOCUMENT EVIDENCE: "
            f"{e['filename']}, page {e['page']}:\n{e['excerpt']}"
            for e in state["evidence"]
        )
        memory_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in [*state["recalled"], *state["history"]]
        )
        prefix = (
            f"Original question: {state['current_message']}\n"
            f"Resolved retrieval question: {state['rewritten_question']}\n"
            "UNTRUSTED CONVERSATIONAL CONTEXT (reference resolution only; not source evidence):\n"
        )
        suffix = (
            "\nUse only DOCUMENT EVIDENCE for factual claims. "
            "Attribute contradictory claims to their respective sources. "
            "Use numbered lists when listing techniques for unambiguous later references."
        )
        memory_text = truncate(
            memory_text + "\nOlder synopsis: " + state["summary"],
            max(0, settings.chat_context_tokens - token_count(context + prefix + suffix) - 300),
        )
        prompt = prefix + memory_text + suffix
        if token_count(prompt + context) + 200 > settings.chat_context_tokens:
            raise HTTPException(422, "Question exceeds the configured context budget; shorten it")
        start = perf_counter()
        result = normalize_citations(resources.generator.answer(prompt, context))
        timings["generation"] = (perf_counter() - start) * 1000
        if token_count(result) > 6000:
            raise HTTPException(502, "Answer exceeds the response limit; ask a narrower question")
        if unsafe_output(
            result,
            [
                settings.jwt_secret.get_secret_value(),
                settings.gemini_api_key.get_secret_value(),
                settings.s3_secret_key.get_secret_value(),
                settings.openai_api_key.get_secret_value(),
                settings.qdrant_api_key.get_secret_value(),
            ],
        ):
            raise HTTPException(
                502, "Answer failed the output safety checks; please rephrase your question"
            )
        return {"generation": result}

    def verify(state: ConversationState) -> dict[str, Any]:
        if state["generation"].strip() == ABSTENTION:
            return {"citations": [], "errors": [*state["errors"], "model_abstained"]}
        if not state["evidence"] or state["clarification"]:
            return {"citations": []}
        cited = {int(number) for number in re.findall(r"\[(\d+)\]", state["generation"])}
        if not cited or not cited.issubset({e["source"] for e in state["evidence"]}):
            EVENTS.labels("citation.validation", "failed").inc()
            raise HTTPException(502, "Model returned an answer without valid source references")
        return {"citations": [e for e in state["evidence"] if e["source"] in cited]}

    def persist(state: ConversationState) -> dict[str, Any]:
        EVENTS.labels(
            "chat.continuity",
            "clarification"
            if state["clarification"] and state["is_followup"]
            else "resolved"
            if state["is_followup"]
            else "standalone",
        ).inc()
        VALUES.labels("evidence_count").observe(len(state["citations"]))
        for category in state["errors"]:
            EVENTS.labels("chat.signal", category).inc()
        position = (
            db.scalar(
                select(func.coalesce(func.max(Message.position), 0)).where(
                    Message.conversation_id == conversation.id
                )
            )
            or 0
        )
        metadata = {
            "scope_version": conversation.scope_version,
            "timings_ms": dict(timings),
            "summary_version": state["summary_version"],
            "budgets": state["budgets"],
            "followup": state["is_followup"],
            "errors": state["errors"],
            "retrieval_metrics": state["plan"].get("retrieval_metrics", {}),
        }
        reply = Message(
            conversation_id=conversation.id,
            position=position + 2,
            role="assistant",
            request_id=question.request_id,
            content=state["generation"],
            citations=state["citations"],
            turn_metadata=metadata,
        )
        db.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    position=position + 1,
                    role="user",
                    request_id=question.request_id,
                    content=question.content,
                    citations=[],
                    turn_metadata={"scope_version": conversation.scope_version},
                ),
                reply,
            ]
        )
        if not state["clarification"]:
            conversation.active_topic = state["topic"]
            methods = answer_methods(state["generation"])
            if methods:
                conversation.references = {"methods": methods, "answer_position": position + 2}
            elif state["topic"] != state.get("references", {}).get("topic", state["topic"]):
                conversation.references = {}
            conversation.references = {**conversation.references, "topic": state["topic"]}
        if conversation.title == "New conversation":
            conversation.title = question.content.strip()[:120]
        db.flush()
        return {
            "response_id": str(reply.id),
            "topic": conversation.active_topic,
            "references": conversation.references,
            "history": [],
            "recalled": [],
            "summary": "",
            "current_message": "",
            "rewritten_question": "",
            "resolved_references": {},
            "generation": "",
            "evidence": [],
            "citations": [],
            "timings_ms": timings,
        }

    graph = StateGraph(ConversationState)
    nodes = {
        "validate": validate,
        "context": memory,
        "resolve": references,
        "rewrite": rewrite,
        "plan": plan,
        "retrieve": retrieval,
        "select": selection,
        "generate": generate,
        "verify": verify,
        "persist": persist,
    }
    for name, node in nodes.items():
        graph.add_node(name, observed("graph." + name)(node))
    graph.add_edge(START, "validate")
    for first, second in [
        ("validate", "context"),
        ("context", "resolve"),
        ("resolve", "rewrite"),
        ("rewrite", "plan"),
        ("retrieve", "select"),
        ("select", "generate"),
        ("generate", "verify"),
        ("verify", "persist"),
    ]:
        graph.add_edge(first, second)
    graph.add_conditional_edges(
        "plan", lambda s: "generate" if s.get("clarification") else "retrieve"
    )
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=saver)


def initial_state(
    conversation: Conversation, documents: list[Document], question: Question, resources: Resources
) -> ConversationState:
    settings = resources.settings
    return ConversationState(
        user_id=str(conversation.user_id),
        conversation_id=str(conversation.id),
        document_ids=[str(doc.id) for doc in documents],
        scope_version=conversation.scope_version,
        current_message=question.content,
        topic=conversation.active_topic
        if safe_memory(conversation.active_topic, settings.security_block_threshold)
        else "",
        references=conversation.references
        if safe_memory(conversation.references, settings.security_block_threshold)
        else {},
        history=[],
        recalled=[],
        summary="",
        summary_version=0,
        covered_through=0,
        resolved_references={},
        rewritten_question=question.content,
        clarification="",
        is_followup=False,
        plan={},
        evidence=[],
        generation="",
        citations=[],
        errors=[],
        budgets={
            "context_tokens": settings.chat_context_tokens,
            "history_tokens": settings.chat_history_tokens,
            "evidence_tokens": settings.chat_evidence_tokens,
        },
        timings_ms={},
        response_id="",
    )
