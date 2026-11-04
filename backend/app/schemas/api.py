from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class ConversationIn(Schema):
    title: str = Field(default="New conversation", min_length=1, max_length=120)
    document_ids: list[UUID] = Field(min_length=1, max_length=20)


class ConversationOut(Schema):
    id: UUID
    title: str
    created_at: datetime


class Question(Schema):
    content: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    request_id: UUID


class Citation(Schema):
    source: int
    document_id: UUID
    filename: str
    page: int
    excerpt: str


class MessageOut(Schema):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation]
    created_at: datetime
