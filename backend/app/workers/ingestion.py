"""Durable SQL job state shared by Dramatiq delivery and isolated integration tests."""

import hashlib
import logging
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from qdrant_client import models as qm
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from backend.app.models.entities import (
    Document,
    DocumentAsset,
    IngestionJob,
    PageExtraction,
    SearchChunk,
    now,
)
from backend.app.rag.extraction import (
    InvalidDocument,
    ProcessingCancelled,
    ProcessingDependencyError,
    extract_pages,
    inspect_pdf,
)
from backend.app.rag.types import embedding_fingerprint, structured_chunks
from backend.app.rag.vectors import index_knowledge, tenant_filter
from backend.app.services.resources import GeminiGenerator, Resources, download_object

logger = logging.getLogger(__name__)


def _remove_content(db: Session, resources: Resources, document: Document) -> None:
    collections = set(
        db.scalars(
            select(IngestionJob.vector_collection).where(
                IngestionJob.document_id == document.id, IngestionJob.vector_collection.is_not(None)
            )
        )
    ) | {document.index_collection, resources.settings.qdrant_collection}
    for collection in filter(None, collections):
        if resources.qdrant.collection_exists(collection):
            resources.qdrant.delete(
                collection,
                points_selector=qm.FilterSelector(
                    filter=tenant_filter(document.user_id, [document.id])
                ),
                wait=True,
            )
    for asset in db.scalars(select(DocumentAsset).where(DocumentAsset.document_id == document.id)):
        resources.store.delete(asset.object_key)
    resources.store.delete(document.object_key)
    db.execute(delete(PageExtraction).where(PageExtraction.document_id == document.id))
    db.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document.id))
    db.execute(delete(IngestionJob).where(IngestionJob.document_id == document.id))
    db.delete(document)
    db.commit()


def process_one(db: Session, resources: Resources, job_id: UUID | None = None) -> bool:
    statement = select(IngestionJob).where(
        IngestionJob.status.in_(["queued", "running"]), IngestionJob.available_at <= now()
    )
    if job_id:
        statement = statement.where(IngestionJob.id == job_id)
    job = db.scalar(
        statement.order_by(IngestionJob.created_at).with_for_update(skip_locked=True).limit(1)
    )
    if not job:
        db.rollback()
        return False
    lock_connection = None
    lock_number = int.from_bytes(job.document_id.bytes[:8], signed=True)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        assert isinstance(bind, Engine)
        lock_connection = bind.connect()
        locked = lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_number}
        )
        if not locked:
            lock_connection.close()
            db.rollback()
            return False
    token = str(uuid4())
    job.status, job.stage, job.run_token = "running", "inspecting", token
    job.attempts += 1
    job.available_at = now() + timedelta(minutes=10)
    document_id, identifier = job.document_id, job.id
    db.commit()
    started = time.monotonic()

    def checkpoint(stage: str | None = None, page: int | None = None) -> None:
        db.flush()
        db.expire_all()
        current = db.get(IngestionJob, identifier)
        document = db.get(Document, document_id)
        if not current or not document or current.run_token != token:
            raise ProcessingCancelled()
        if current.cancel_requested or (document.status == "deleting" and current.kind == "ingest"):
            raise ProcessingCancelled()
        if time.monotonic() - started > resources.settings.ingestion_timeout_seconds:
            raise ProcessingDependencyError("Ingestion deadline exceeded")
        if stage:
            current.stage = stage
        if page is not None:
            current.pages_processed = page
        current.available_at = now() + timedelta(minutes=10)
        db.commit()

    try:
        document = db.get(Document, document_id)
        if not document:
            return True
        owner_id = document.user_id
        if (
            document.status == "deleting"
            or job.kind == "delete"
            or (job.kind == "cleanup" and document.status == "uploading")
        ):
            _remove_content(db, resources, document)
            return True
        if job.kind == "cleanup":
            job.status = "succeeded"
            db.commit()
            return True
        checkpoint()
        if job.vector_collection and job.vector_collection != resources.settings.qdrant_collection:
            raise InvalidDocument("Index configuration changed; create an authorized retry job")
        job.vector_collection = resources.settings.qdrant_collection
        document.status, document.error = "queued", None
        document.chunk_count = document.table_count = document.figure_count = 0
        db.commit()
        vision = None
        if document.extraction_mode == "enhanced-multimodal" and resources.settings.vision_enabled:
            vision_settings = resources.settings.model_copy(
                update={"gemini_model": resources.settings.vision_model}
            )
            vision = GeminiGenerator(vision_settings).describe

        def save_asset(
            page: int, kind: str, data: bytes, caption: str, details: dict[str, Any]
        ) -> str:
            checkpoint("extracting")
            asset_id = uuid5(document_id, f"{page}:{kind}:{hashlib.sha256(data).hexdigest()}")
            extension = details.get("extension", "png")
            if extension not in {"png", "jpeg", "jpg", "jp2", "tiff", "bmp"}:
                extension = "bin"
            key = f"{owner_id}/{document_id}/assets/{asset_id}.{extension}"
            asset = db.get(DocumentAsset, asset_id)
            if not asset:
                asset = DocumentAsset(
                    id=asset_id,
                    document_id=document_id,
                    page=page,
                    kind=kind,
                    object_key=key,
                    caption=caption,
                    details=details,
                )
                db.add(asset)
                db.commit()
            if not asset.available:
                resources.store.put(key, data)
                asset.available = True
                db.commit()
            return str(asset_id)

        with tempfile.TemporaryDirectory(prefix="smartrag-") as directory:
            source = Path(directory) / "source.pdf"
            download_object(resources.store, document.object_key, source)
            job.total_pages = inspect_pdf(source, resources.settings)
            document.page_count = job.total_pages
            db.commit()
            for result in extract_pages(
                source, resources.settings, document.extraction_mode, save_asset, vision, checkpoint
            ):
                checkpoint("normalizing")
                record = db.get(PageExtraction, (document_id, result.page))
                if not record:
                    record = PageExtraction(document_id=document_id, page=result.page)
                    db.add(record)
                record.strategy, record.quality = result.strategy, result.quality
                record.content = [element.to_dict() for element in result.elements]
                for element in result.elements:
                    if element.asset_id and element.model_derived:
                        asset = db.get(DocumentAsset, UUID(element.asset_id))
                        if asset:
                            asset.model_derived = True
                            asset.details = {
                                **asset.details,
                                "vision_model": resources.settings.vision_model,
                                "description": element.text,
                            }
                record.warnings, record.processed_at = result.warnings, now()
                db.commit()
                checkpoint("chunking")
                chunks = structured_chunks(result.elements, resources.settings)
                checkpoint("embedding")
                index_knowledge(
                    resources,
                    document.user_id,
                    document_id,
                    document.filename,
                    token,
                    chunks,
                    db=db,
                )
                document.chunk_count += len(chunks)
                document.table_count += sum(e.kind == "table" for e in result.elements)
                document.figure_count += sum(e.kind == "figure" for e in result.elements)
                checkpoint("extracting", result.page)
            if not document.chunk_count:
                raise InvalidDocument("No usable text, table or figure content could be extracted")
        checkpoint("publishing")
        document = db.scalar(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = db.scalar(
            select(IngestionJob)
            .where(IngestionJob.id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not document
            or not job
            or job.run_token != token
            or job.cancel_requested
            or document.status == "deleting"
        ):
            raise ProcessingCancelled()
        selector = tenant_filter(document.user_id, [document_id])
        selector.must_not = [qm.FieldCondition(key="run_token", match=qm.MatchValue(value=token))]
        resources.qdrant.delete(
            resources.settings.qdrant_collection,
            points_selector=qm.FilterSelector(filter=selector),
            wait=True,
        )
        document.status, document.active_run = "ready", token
        db.execute(
            delete(SearchChunk).where(
                SearchChunk.document_id == document_id, SearchChunk.run_token != token
            )
        )
        document.index_fingerprint = embedding_fingerprint(resources.settings)
        document.index_collection = resources.settings.qdrant_collection
        job.status, job.stage, job.error = "succeeded", "completed", None
        db.commit()
    except Exception as error:
        db.rollback()
        document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
        job = db.get(IngestionJob, identifier, populate_existing=True)
        if document and job and job.run_token == token:
            cancelled = isinstance(error, ProcessingCancelled)
            retryable = not isinstance(error, (InvalidDocument, ProcessingCancelled, ValueError))
            retry = (
                retryable and job.attempts < resources.settings.ingestion_max_attempts
            ) or document.status == "deleting"
            job.status = "queued" if retry else "failed"
            job.stage = "retry-wait" if retry else ("cancelled" if cancelled else "failed")
            job.retryable = retryable
            job.error = (
                "Processing cancelled"
                if cancelled
                else "Invalid or unsupported PDF/index configuration"
                if not retryable
                else "Processing dependency failed or timed out; check OCR, model and storage"
            )
            job.available_at = now() + timedelta(seconds=min(300, 10 * 2 ** min(job.attempts, 5)))
            if job.kind == "cleanup":
                document.status, job.status = "deleting", "queued"
            elif document.status != "deleting":
                document.status = "queued" if retry else "failed"
            document.error = job.error
            db.commit()
        logger.warning(
            "Ingestion attempt ended; job_id=%s failure_type=%s (private details suppressed)",
            identifier,
            type(error).__name__,
        )
    finally:
        if lock_connection is not None:
            lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_number})
            lock_connection.close()
    return True
