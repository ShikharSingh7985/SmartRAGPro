from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Credentials(Schema):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)


class UserOut(Schema):
    id: UUID
    email: str


class TokenOut(Schema):
    access_token: str
    token_type: str = "bearer"


class DocumentOut(Schema):
    id: UUID
    filename: str
    status: str
    page_count: int
    error: str | None
    created_at: datetime
    extraction_mode: str
    chunk_count: int
    table_count: int
    figure_count: int


class JobOut(Schema):
    id: UUID
    document_id: UUID
    status: str
    stage: str
    pages_processed: int
    total_pages: int
    attempts: int
    error: str | None
    retryable: bool
    cancel_requested: bool
    updated_at: datetime

    @field_serializer("status")
    def public_status(self, value: str) -> str:
        return {"running": "processing", "succeeded": "completed"}.get(value, value)


class AssetOut(Schema):
    id: UUID
    document_id: UUID
    page: int
    kind: str
    caption: str
    model_derived: bool


class ConversationIn(Schema):
    title: str = Field(default="New conversation", min_length=1, max_length=120, pattern=r"\S")
    document_ids: list[UUID] = Field(min_length=1, max_length=20)


class ConversationOut(Schema):
    id: UUID
    title: str
    created_at: datetime
    scope_version: int
    source_warning: str | None


class ConversationUpdate(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"\S")
    document_ids: list[UUID] | None = Field(default=None, max_length=20)


class ConversationDetail(ConversationOut):
    document_ids: list[UUID]


class Question(Schema):
    content: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    request_id: UUID


class Citation(Schema):
    source: int
    document_id: UUID
    filename: str
    page: int
    excerpt: str
    page_end: int | None = None
    content_type: str = "text"
    asset_id: UUID | None = None
    model_derived: bool = False
    chunk_id: str | None = None
    element_id: str | None = None
    section_heading: str | None = None
    preview_path: str | None = None


class MessageOut(Schema):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation]
    created_at: datetime


class ConversationExport(Schema):
    conversation: ConversationDetail
    messages: list[MessageOut]
    next_offset: int | None
