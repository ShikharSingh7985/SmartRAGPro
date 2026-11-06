from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.v1.routes import owned_document
from backend.app.core.config import get_settings
from backend.app.core.security import current_user, lock_active_owner
from backend.app.db.session import get_db
from backend.app.models.entities import (
    Document,
    DocumentAsset,
    IngestionJob,
    PageExtraction,
    SecurityInspection,
    User,
    now,
)
from backend.app.schemas.api import AssetOut, JobOut
from backend.app.services.resources import Resources, get_resources

router = APIRouter(prefix="/api/v1/documents", tags=["ingestion"])


def ingestion_quota(db: Session, user: User) -> None:
    # Match upload/account lock order and bound explicit retries independently of broker retries.
    lock_active_owner(db, user.id)
    recent = (
        db.scalar(
            select(func.count(IngestionJob.id))
            .join(Document)
            .where(
                Document.user_id == user.id,
                IngestionJob.kind == "ingest",
                IngestionJob.created_at >= now() - timedelta(minutes=10),
            )
        )
        or 0
    )
    if recent >= 20:
        raise HTTPException(429, "Ingestion request quota exceeded; retry later")
    active = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.user_id == user.id, Document.status.in_(["queued", "uploading"])
            )
        )
        or 0
    )
    if active >= get_settings().max_active_jobs_per_user:
        raise HTTPException(429, "Concurrent ingestion quota exceeded; wait for existing jobs")


@router.get("/{document_id}/security")
def security_results(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[dict[str, Any]]:
    owned_document(db, document_id, user.id)
    return [
        {
            "object_id": item.object_id,
            "stage": item.stage,
            "score": item.score,
            "decision": item.decision,
            "reasons": item.reasons,
            "policy_version": item.policy_version,
        }
        for item in db.scalars(
            select(SecurityInspection)
            .where(
                SecurityInspection.document_id == document_id, SecurityInspection.user_id == user.id
            )
            .limit(1000)
        )
    ]


def accessible(db: Session, document_id: UUID, user_id: UUID) -> Document:
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.user_id == user_id)
        .with_for_update()
    )
    if not document:
        raise HTTPException(404, "Document not found")
    if document.status in {"deleting", "uploading"}:
        raise HTTPException(409, "Document is not available")
    return document


@router.get("/{document_id}/jobs", response_model=list[JobOut])
def jobs(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[IngestionJob]:
    owned_document(db, document_id, user.id)
    return list(
        db.scalars(
            select(IngestionJob)
            .where(IngestionJob.document_id == document_id, IngestionJob.kind == "ingest")
            .order_by(IngestionJob.created_at.desc())
            .limit(20)
        )
    )


@router.post("/{document_id}/retry", response_model=JobOut, status_code=202)
def retry(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> IngestionJob:
    ingestion_quota(db, user)
    accessible(db, document_id, user.id)
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not document or document.status != "failed":
        raise HTTPException(409, "Only failed or cancelled documents can be retried")
    document.status, document.error = "queued", None
    job = IngestionJob(document_id=document.id)
    db.add(job)
    db.commit()
    return job


@router.post("/{document_id}/reindex", response_model=JobOut, status_code=202)
def reindex(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> IngestionJob:
    ingestion_quota(db, user)
    accessible(db, document_id, user.id)
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not document or document.status != "ready":
        raise HTTPException(409, "Only ready documents can be reindexed")
    document.status, document.error = "queued", None
    job = IngestionJob(document_id=document.id)
    db.add(job)
    db.commit()
    return job


@router.post("/{document_id}/cancel", status_code=202)
def cancel(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, str]:
    document = accessible(db, document_id, user.id)
    if document.status != "queued":
        raise HTTPException(409, "Document has no active ingestion")
    for job in db.scalars(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document_id,
            IngestionJob.kind == "ingest",
            IngestionJob.status.in_(["queued", "running"]),
        )
        .with_for_update()
    ):
        job.cancel_requested = True
    db.commit()
    return {"status": "cancellation-requested"}


@router.get("/{document_id}/pages/{page}")
def extracted_page(
    document_id: UUID, page: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, Any]:
    accessible(db, document_id, user.id)
    record = db.get(PageExtraction, (document_id, page))
    if not record:
        raise HTTPException(404, "Extracted page not found")
    return {
        "page": page,
        "strategy": record.strategy,
        "quality": record.quality,
        "warnings": record.warnings,
        "elements": record.content,
    }


@router.get("/{document_id}/assets", response_model=list[AssetOut])
def assets(
    document_id: UUID,
    page: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[DocumentAsset]:
    accessible(db, document_id, user.id)
    query = select(DocumentAsset).where(
        DocumentAsset.document_id == document_id, DocumentAsset.available.is_(True)
    )
    if page is not None:
        query = query.where(DocumentAsset.page == page)
    return list(db.scalars(query.order_by(DocumentAsset.page).limit(100)))


@router.get("/{document_id}/assets/{asset_id}")
def image(
    document_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    resources: Resources = Depends(get_resources),
) -> Response:
    accessible(db, document_id, user.id)
    asset = db.scalar(
        select(DocumentAsset).where(
            DocumentAsset.document_id == document_id,
            DocumentAsset.id == asset_id,
            DocumentAsset.available.is_(True),
        )
    )
    if not asset:
        raise HTTPException(404, "Asset not found")
    if not asset.object_key.startswith(f"{user.id}/{document_id}/assets/"):
        raise HTTPException(404, "Asset not found")
    try:
        extension = asset.object_key.rsplit(".", 1)[-1]
        media_type = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "jp2": "image/jp2",
            "bmp": "image/bmp",
        }.get(extension, "application/octet-stream")
        return Response(resources.store.get(asset.object_key), media_type=media_type)
    except Exception:
        raise HTTPException(503, "Source image temporarily unavailable") from None


@router.get("/{document_id}/preview/{page}")
def preview(
    document_id: UUID,
    page: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    resources: Resources = Depends(get_resources),
) -> Response:
    document = accessible(db, document_id, user.id)
    if page < 1 or page > document.page_count:
        raise HTTPException(404, "Page not found")
    asset = db.scalar(
        select(DocumentAsset).where(
            DocumentAsset.document_id == document_id,
            DocumentAsset.page == page,
            DocumentAsset.kind == "page_preview",
            DocumentAsset.available.is_(True),
        )
    )
    if not asset:
        raise HTTPException(404, "Preview not yet available; reindex older documents")
    return image(document_id, asset.id, db, user, resources)
