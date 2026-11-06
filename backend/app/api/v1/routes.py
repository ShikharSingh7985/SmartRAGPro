import hashlib
import re
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.conversations.checkpoints import clear_checkpoint
from backend.app.core.config import Settings, get_settings
from backend.app.core.security import (
    current_user,
    dummy_hash,
    hasher,
    lock_active_owner,
    verify_password,
)
from backend.app.db.session import get_db
from backend.app.models.entities import (
    AuditEvent,
    Conversation,
    ConversationDocument,
    ConversationSummary,
    Document,
    IngestionJob,
    Message,
    User,
    now,
)
from backend.app.schemas.api import (
    ConfirmPassword,
    ConversationDetail,
    ConversationExport,
    ConversationIn,
    ConversationOut,
    ConversationUpdate,
    Credentials,
    DocumentOut,
    MessageOut,
    PasswordChange,
    Question,
    RefreshIn,
    TokenOut,
    UserOut,
)
from backend.app.security.rate import account_rate
from backend.app.services.accounts import delete_account
from backend.app.services.chat import answer, owned_conversation
from backend.app.services.resources import Resources, get_resources, upload_stream
from backend.app.services.sessions import issue_pair, revoke, rotate

router = APIRouter(prefix="/api/v1")


@router.post("/auth/register", status_code=201, tags=["auth"])
def register(
    body: Credentials, db: Session = Depends(get_db), resources: Resources = Depends(get_resources)
) -> dict[str, str]:
    account_rate(resources, str(body.email), "register")
    user = User(email=str(body.email).strip().casefold(), password_hash=hasher.hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    db.add(AuditEvent(event="registration_attempt"))
    db.commit()
    return {
        "detail": "If this address is available, your account has been created. "
        "Sign in to continue."
    }


@router.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(
    body: Credentials,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    resources: Resources = Depends(get_resources),
) -> TokenOut:
    account_rate(resources, str(body.email), "login")
    user = db.scalar(
        select(User).where(User.email == str(body.email).strip().casefold()).with_for_update()
    )
    valid = verify_password(body.password, user.password_hash if user else dummy_hash)
    if not user or not valid or not user.is_active or user.deleted_at:
        db.add(AuditEvent(event="login_failed"))
        db.commit()
        raise HTTPException(401, "Incorrect email or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password)
    result = issue_pair(db, user, settings)
    db.add(AuditEvent(actor_id=user.id, event="login_succeeded"))
    db.commit()
    return result


@router.post("/auth/refresh", response_model=TokenOut, tags=["auth"])
def refresh(
    body: RefreshIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> TokenOut:
    return rotate(db, body.refresh_token.get_secret_value(), settings)


@router.post("/auth/password", status_code=204, tags=["auth"])
def change_password(
    body: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    locked = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not locked or not verify_password(
        body.current_password.get_secret_value(), locked.password_hash
    ):
        raise HTTPException(401, "Incorrect email or password")
    locked.password_hash = hasher.hash(body.new_password.get_secret_value())
    revoke(db, locked, "password_changed")
    db.commit()
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(current_user)) -> User:
    return user


@router.delete("/auth/account", status_code=202, tags=["auth"])
def remove_account(
    body: ConfirmPassword, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    locked = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not locked or not verify_password(body.password.get_secret_value(), locked.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    delete_account(db, locked)
    return {"status": "deletion-queued"}


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    locked = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert locked is not None
    revoke(db, locked, "logout")
    db.commit()
    return Response(status_code=204)


def owned_document(db: Session, document_id: UUID, user_id: UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user_id))
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.post("/documents", response_model=DocumentOut, status_code=202, tags=["documents"])
def upload(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    resources: Resources = Depends(get_resources),
    extraction_mode: Literal["auto", "text-first", "ocr-enabled", "enhanced-multimodal"]
    | None = Form(None),
) -> Document:
    extraction_mode = extraction_mode or resources.settings.extraction_mode
    name = (file.filename or "document.pdf").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:255]
    if not name.lower().endswith(".pdf") or file.content_type != "application/pdf":
        raise HTTPException(415, "Only PDF uploads are supported")
    if file.file.read(5) != b"%PDF-":
        raise HTTPException(422, "Upload must be a valid PDF")
    file.file.seek(0)
    digest = hashlib.sha256()
    size = 0
    while block := file.file.read(1024 * 1024):
        size += len(block)
        if size > resources.settings.max_upload_bytes:
            raise HTTPException(413, "PDF exceeds upload size limit")
        digest.update(block)
    file.file.seek(0)
    lock_active_owner(db, user.id)
    existing = db.scalar(
        select(Document).where(
            Document.user_id == user.id,
            Document.content_hash == digest.hexdigest(),
            Document.extraction_mode == extraction_mode,
        )
    )
    if existing:
        return existing
    settings = resources.settings
    count, total = db.execute(
        select(func.count(Document.id), func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.user_id == user.id
        )
    ).one()
    active = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.user_id == user.id, Document.status.in_(["uploading", "queued"])
            )
        )
        or 0
    )
    if (
        count >= settings.max_documents_per_user
        or total + size > settings.max_storage_bytes_per_user
    ):
        raise HTTPException(429, "Document storage quota exceeded")
    if active >= settings.max_active_jobs_per_user:
        raise HTTPException(429, "Concurrent ingestion quota exceeded; wait for existing jobs")
    document_id = uuid4()
    key = f"{user.id}/{document_id}.pdf"
    doc = Document(
        id=document_id,
        user_id=user.id,
        filename=name,
        object_key=key,
        content_hash=digest.hexdigest(),
        extraction_mode=extraction_mode,
        size_bytes=size,
    )
    # Persist pending metadata before external I/O so a failed commit cannot orphan an object.
    doc.status = "uploading"
    db.add(doc)
    db.flush()
    db.add(
        IngestionJob(
            document_id=document_id,
            kind="cleanup",
            status="queued",
            available_at=now() + timedelta(minutes=10),
        )
    )
    db.commit()
    try:
        locked = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
        if locked is None or locked.status != "uploading":
            raise HTTPException(409, "Upload expired; please retry")
        upload_stream(resources.store, key, file.file)
        locked.status = "queued"
        db.execute(delete(IngestionJob).where(IngestionJob.document_id == document_id))
        db.add(IngestionJob(document_id=document_id))
        db.commit()
    except Exception as exc:
        db.rollback()
        # Durable cleanup job removes partially uploaded objects, including after a crash.
        raise HTTPException(503, "Upload storage unavailable; retry later") from exc
    return doc


@router.get("/documents", response_model=list[DocumentOut], tags=["documents"])
def documents(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = 100,
    offset: int = 0,
) -> list[Document]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    return list(
        db.scalars(
            select(Document)
            .where(Document.user_id == user.id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/documents/{document_id}", response_model=DocumentOut, tags=["documents"])
def document(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Document:
    return owned_document(db, document_id, user.id)


@router.delete("/documents/{document_id}", status_code=202, tags=["documents"])
def remove_document(
    document_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict[str, str]:
    owned_document(db, document_id, user.id)
    # Match chat lock order: conversation before document. Lock all associations before deletion.
    conversations = list(
        db.scalars(
            select(Conversation)
            .join(ConversationDocument)
            .where(ConversationDocument.document_id == document_id, Conversation.user_id == user.id)
            .order_by(Conversation.id)
            .with_for_update()
        )
    )
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.user_id == user.id)
        .with_for_update()
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status != "deleting":
        doc.status = "deleting"
        # Remove derived text as well as citations: answers may contain sensitive source content.
        for conversation in conversations:
            db.execute(delete(Message).where(Message.conversation_id == conversation.id))
            db.execute(
                delete(ConversationSummary).where(
                    ConversationSummary.conversation_id == conversation.id
                )
            )
            clear_checkpoint(db, conversation)
            db.execute(
                delete(ConversationDocument).where(
                    ConversationDocument.conversation_id == conversation.id,
                    or_(
                        ConversationDocument.document_id == document_id,
                        ConversationDocument.active.is_(False),
                    ),
                )
            )
            conversation.scope_version += 1
            conversation.active_topic = ""
            conversation.title = "Recovered conversation"
            conversation.references = {}
            conversation.source_warning = (
                "A source was deleted. Derived history was cleared for privacy. "
                "Select available sources to continue."
            )
        db.add(IngestionJob(document_id=doc.id, kind="delete"))
        db.commit()
    return {"status": "deleting"}


@router.post(
    "/conversations", response_model=ConversationOut, status_code=201, tags=["conversations"]
)
def create_conversation(
    body: ConversationIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Conversation:
    lock_active_owner(db, user.id)
    ids = set(body.document_ids)
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.id.in_(ids), Document.user_id == user.id, Document.status == "ready")
            .order_by(Document.id)
            .with_for_update()
        )
    )
    if len(docs) != len(ids):
        raise HTTPException(404, "One or more ready documents not found")
    conversation = Conversation(user_id=user.id, title=body.title)
    db.add(conversation)
    db.flush()
    db.add_all(
        [ConversationDocument(conversation_id=conversation.id, document_id=doc.id) for doc in docs]
    )
    db.commit()
    return conversation


@router.get("/conversations", response_model=list[ConversationOut], tags=["conversations"])
def conversations(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = 100,
    offset: int = 0,
) -> list[Conversation]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.get(
    "/conversations/{conversation_id}", response_model=ConversationDetail, tags=["conversations"]
)
def conversation_detail(
    conversation_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> ConversationDetail:
    conv = owned_conversation(db, conversation_id, user.id)
    ids = list(
        db.scalars(
            select(ConversationDocument.document_id).where(
                ConversationDocument.conversation_id == conversation_id,
                ConversationDocument.active.is_(True),
            )
        )
    )
    return ConversationDetail(**ConversationOut.model_validate(conv).model_dump(), document_ids=ids)


@router.patch(
    "/conversations/{conversation_id}", response_model=ConversationDetail, tags=["conversations"]
)
def update_conversation(
    conversation_id: UUID,
    body: ConversationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ConversationDetail:
    conv = owned_conversation(db, conversation_id, user.id, lock=True)
    if body.title is not None:
        conv.title = body.title.strip()
    if body.document_ids is not None:
        ids = set(body.document_ids)
        docs = list(
            db.scalars(
                select(Document)
                .where(
                    Document.id.in_(ids), Document.user_id == user.id, Document.status == "ready"
                )
                .order_by(Document.id)
                .with_for_update()
            )
        )
        if len(docs) != len(ids):
            raise HTTPException(404, "One or more ready documents not found")
        previous = set(
            db.scalars(
                select(ConversationDocument.document_id).where(
                    ConversationDocument.conversation_id == conv.id,
                    ConversationDocument.active.is_(True),
                )
            )
        )
        if ids != previous:
            clear_checkpoint(db, conv)
            db.execute(
                delete(ConversationSummary).where(ConversationSummary.conversation_id == conv.id)
            )
            db.execute(
                update(ConversationDocument)
                .where(ConversationDocument.conversation_id == conv.id)
                .values(active=False)
            )
            for doc in docs:
                association = db.get(ConversationDocument, (conv.id, doc.id))
                if association:
                    association.active = True
                else:
                    db.add(
                        ConversationDocument(
                            conversation_id=conv.id, document_id=doc.id, active=True
                        )
                    )
            conv.scope_version += 1
            conv.active_topic, conv.references = "", {}
            conv.source_warning = (
                "Document scope changed. Previous messages remain visible; "
                "new turns use the current scope only."
            )
    db.commit()
    return conversation_detail(conversation_id, db, user)


@router.delete("/conversations/{conversation_id}", status_code=204, tags=["conversations"])
def delete_conversation(
    conversation_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    conv = owned_conversation(db, conversation_id, user.id, lock=True)
    clear_checkpoint(db, conv)
    db.delete(conv)
    db.commit()
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/summary/refresh", tags=["conversations"])
def refresh_summary(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    resources: Resources = Depends(get_resources),
) -> dict[str, int]:
    from backend.app.conversations.memory import reconstruct

    conv = owned_conversation(db, conversation_id, user.id, lock=True)
    db.execute(delete(ConversationSummary).where(ConversationSummary.conversation_id == conv.id))
    result = reconstruct(db, conv, "", resources.settings)
    db.commit()
    return {"version": result["summary_version"], "covered_through": result["covered_through"]}


@router.get(
    "/conversations/{conversation_id}/export",
    response_model=ConversationExport,
    tags=["conversations"],
)
def export_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = 100,
    offset: int = 0,
) -> ConversationExport:
    detail = conversation_detail(conversation_id, db, user)
    page = messages(conversation_id, db, user, limit, offset)
    return ConversationExport(
        conversation=detail,
        messages=[MessageOut.model_validate(message) for message in page],
        next_offset=offset + len(page) if len(page) == limit else None,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
    tags=["conversations"],
)
def messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = 100,
    offset: int = 0,
) -> list[Message]:
    owned_conversation(db, conversation_id, user.id)
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.position)
            .limit(limit)
            .offset(offset)
        )
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=201,
    tags=["conversations"],
)
def ask(
    conversation_id: UUID,
    body: Question,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    resources: Resources = Depends(get_resources),
) -> Message:
    try:
        return answer(db, resources, conversation_id, user.id, body)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            503,
            "Answer dependency unavailable; retry with the same request_id",
            headers={"Retry-After": "10"},
        ) from exc
