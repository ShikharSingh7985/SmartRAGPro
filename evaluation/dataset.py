"""Editable synthetic labels; generated provenance is never human review."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class Chunk(BaseModel):
    id: str
    document_id: str
    filename: str
    page: int = Field(ge=1)
    content_type: str
    text: str


class Query(BaseModel):
    id: str
    text: str
    document_ids: list[str]
    relevant_ids: list[str]
    expected_answer: str
    answerable: bool
    category: str
    split: str
    context: list[dict[str, str]] = Field(default_factory=list)
    provenance: str = "synthetic author-generated; not independently human reviewed"
    reviewed_by: str | None = None


class Dataset(BaseModel):
    version: str
    chunks: list[Chunk]
    queries: list[Query]

    @model_validator(mode="after")
    def valid_labels(self):
        chunks = {c.id: c for c in self.chunks}
        if len(chunks) != len(self.chunks) or len({q.id for q in self.queries}) != len(
            self.queries
        ):
            raise ValueError("Duplicate IDs")
        documents = {c.document_id for c in self.chunks}
        for query in self.queries:
            if query.split not in {"validation", "test"} or not query.document_ids:
                raise ValueError("Invalid split or empty scope")
            if not set(query.document_ids) <= documents:
                raise ValueError("Unknown source document")
            if query.answerable != bool(query.relevant_ids):
                raise ValueError("Answerability and relevance labels disagree")
            for identifier in query.relevant_ids:
                if (
                    identifier not in chunks
                    or chunks[identifier].document_id not in query.document_ids
                ):
                    raise ValueError("Relevant evidence outside selected scope")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load(path: str | Path = "evaluation/data/synthetic.json") -> Dataset:
    return Dataset.model_validate_json(Path(path).read_text(encoding="utf-8"))


def build() -> Dataset:
    topics = [
        ("overfitting", "memorizing training noise", "regularization", "high variance"),
        (
            "random forests",
            "combining decision trees",
            "feature subsampling",
            "limited interpretability",
        ),
        (
            "gradient descent",
            "iteratively reducing a loss",
            "learning rate scheduling",
            "sensitivity to step size",
        ),
        ("dropout", "randomly disabling training units", "mask sampling", "slower convergence"),
        (
            "principal components",
            "projecting onto high variance directions",
            "standardizing features",
            "loss of interpretability",
        ),
        (
            "support vector machines",
            "maximizing the classification margin",
            "kernel selection",
            "expensive training",
        ),
        (
            "naive Bayes",
            "assuming conditional independence",
            "Laplace smoothing",
            "correlated feature assumptions",
        ),
        (
            "k-means",
            "assigning points to centroids",
            "multiple initializations",
            "sensitivity to outliers",
        ),
        (
            "neural networks",
            "learning layered representations",
            "early stopping",
            "large training costs",
        ),
        (
            "regularization",
            "penalizing model complexity",
            "L2 weight penalties",
            "underfitting with excessive strength",
        ),
    ]
    chunks, queries = [], []
    for index, (topic, definition, method, limitation) in enumerate(topics):
        doc, code = f"book-{index:02}", f"ZX-{47 + index}"
        accuracy, peak, hours = 81 + index, 14 + index, 3 + index
        pages = [
            (
                "text",
                f"Chapter 1: {topic}. This synthetic handbook defines {topic} as {definition}. "
                f"The recommended intervention is {method}.",
            ),
            (
                "table",
                f"Table 3: {topic} benchmark. Headers: Approach | "
                "Accuracy percent | Training hours. "
                f"Row: Model A | {accuracy - 4} | {hours + 2}. "
                f"Row: Model B | {accuracy} | {hours}. "
                f"Model B uses {method}. Values are synthetic, not scientific findings.",
            ),
            (
                "figure",
                f"Figure 2: {topic} validation curve. "
                "Chart x-axis: epoch, y-axis: validation score. "
                f"At epoch 1 the score is 5; at epoch 2 it is {peak}; at epoch 3 it is 8. "
                "The maximum is epoch 2. This is a visible-value transcription, "
                "not model-derived vision.",
            ),
            (
                "text",
                f"Chapter 5: applying {topic}. Workflow: normalize inputs, apply {method}, "
                "evaluate held-out examples. Do not select parameters using the evaluation labels.",
            ),
            (
                "text",
                f"Chapter 6: limitations of {topic}. The main drawback is {limitation}. "
                "Monitoring held-out results helps identify this tradeoff.",
            ),
            (
                "text",
                f"Appendix {code}: the {topic} maintenance record. Error code {code} requires "
                f"restarting the calibration stage. The calibration interval is {index + 11} days. "
                "This identifier is case-insensitive.",
            ),
        ]
        for page, (kind, text) in enumerate(pages, 1):
            chunks.append(
                Chunk(
                    id=f"{doc}-p{page}",
                    document_id=doc,
                    filename=f"{doc}.pdf",
                    page=page,
                    content_type=kind,
                    text=text,
                )
            )
        specifications = [
            ("factual", f"What does {topic} mean?", [1], definition),
            ("explanatory", f"Explain the recommended intervention for {topic}.", [1, 4], method),
            (
                "table",
                f"What accuracy and training hours does Model B achieve in Table 3 for {topic}?",
                [2],
                f"{accuracy} percent; {hours} hours",
            ),
            (
                "figure",
                f"At which epoch does Figure 2 for {topic} reach its maximum "
                "and what is its score?",
                [3],
                f"epoch 2; {peak}",
            ),
            (
                "cross_page",
                f"Define {topic} and name its main drawback.",
                [1, 5],
                f"{definition}; {limitation}",
            ),
            (
                "multi_hop",
                f"Which {topic} approach is more accurate in Table 3 "
                "and which intervention does it use?",
                [1, 2],
                f"Model B; {method}",
            ),
            ("followup", "How is it applied in chapter 5?", [4], method),
            (
                "identifier",
                f"What action resolves {code}?",
                [6],
                "restarting the calibration stage",
            ),
        ]
        scope = [doc, f"book-{(index + 1) % 10:02}", f"book-{(index + 2) % 10:02}"]
        for number, (category, question, pages_, answer) in enumerate(specifications):
            queries.append(
                Query(
                    id=f"q{index:02}-{number}",
                    text=question,
                    document_ids=scope,
                    relevant_ids=[f"{doc}-p{p}" for p in pages_],
                    expected_answer=answer,
                    answerable=True,
                    category=category,
                    split="validation" if index < 4 else "test",
                    context=[{"role": "user", "content": f"What is {topic}?"}]
                    if category == "followup"
                    else [],
                )
            )
        for category, question in [
            ("ambiguous", "Which of those is better?"),
            ("unanswerable", f"What is the author's phone number in the {topic} book?"),
        ]:
            queries.append(
                Query(
                    id=f"q{index:02}-{category}",
                    text=question,
                    document_ids=[doc],
                    relevant_ids=[],
                    expected_answer="Request clarification"
                    if category == "ambiguous"
                    else "Insufficient evidence",
                    answerable=False,
                    category=category,
                    split="validation" if index < 4 else "test",
                )
            )
    for index in [0, 1, 2, 4, 5, 6, 7, 8]:
        first, second = topics[index], topics[index + 1]
        queries.append(
            Query(
                id=f"cross-{index}",
                text=f"Compare the main drawbacks of {first[0]} and {second[0]}.",
                document_ids=[f"book-{index:02}", f"book-{index + 1:02}"],
                relevant_ids=[f"book-{index:02}-p5", f"book-{index + 1:02}-p5"],
                expected_answer=first[3] + "; " + second[3],
                answerable=True,
                category="cross_document",
                split="validation" if index < 3 else "test",
            )
        )
    return Dataset(version="synthetic-v1", chunks=chunks, queries=queries)


if __name__ == "__main__":
    path = Path("evaluation/data/synthetic.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build().model_dump(), indent=2), encoding="utf-8")
    print(f"Validated {len(load(path).queries)} synthetic queries")
