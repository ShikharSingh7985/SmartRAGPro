import hashlib
import re
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.core.security import (
    current_user,
    dummy_hash,
    hasher,
    issue_token,
    verify_password,
)
from backend.app.db.session import get_db
from backend.app.models.entities import (
    Conversation,
    ConversationDocument,
    Document,
    IngestionJob,
    Message,
    User,
    now,
)
from backend.app.schemas.api import (
    ConversationIn,
    ConversationOut,
    Credentials,
    DocumentOut,
    MessageOut,
    Question,
    TokenOut,
    UserOut,
)
from backend.app.services.chat import answer, owned_conversation
from backend.app.services.resources import Resources, get_resources, upload_stream

router = APIRouter(prefix="/api/v1")


@router.post("/auth/register", response_model=UserOut, status_code=201, tags=["auth"])
def register(body: Credentials, db: Session = Depends(get_db)) -> User:
    user = User(email=str(body.email).strip().casefold(), password_hash=hasher.hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email is already registered") from exc
    return user


@router.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(
    body: Credentials, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> TokenOut:
    user = db.scalar(select(User).where(User.email == str(body.email).strip().casefold()))
    valid = verify_password(body.password, user.password_hash if user else dummy_hash)
    if not user or not valid:
        raise HTTPException(401, "Incorrect email or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password)
        db.commit()
    return TokenOut(access_token=issue_token(user, settings))


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    db.execute(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))
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
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(
        select(Document).where(
            Document.user_id == user.id,
            Document.content_hash == digest.hexdigest(),
            Document.extraction_mode == extraction_mode,
        )
    )
    if existing:
        return existing
    document_id = uuid4()
    key = f"{user.id}/{document_id}.pdf"
    doc = Document(
        id=document_id,
        user_id=user.id,
        filename=name,
        object_key=key,
        content_hash=digest.hexdigest(),
        extraction_mode=extraction_mode,
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
                delete(ConversationDocument).where(
                    ConversationDocument.conversation_id == conversation.id
                )
            )
            db.delete(conversation)
        db.add(IngestionJob(document_id=doc.id, kind="delete"))
        db.commit()
    return {"status": "deleting"}


@router.post(
    "/conversations", response_model=ConversationOut, status_code=201, tags=["conversations"]
)
def create_conversation(
    body: ConversationIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Conversation:
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
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            503, "Answer dependency unavailable; retry with the same request_id"
        ) from exc
