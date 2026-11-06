from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str
    jwt_secret: SecretStr
    jwt_issuer: str = "smartrag-pro"
    jwt_audience: str = "smartrag-pro-api"
    access_token_minutes: int = Field(default=30, ge=1, le=1440)
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    embedding_provider: Literal["google", "openai", "local"] = "google"
    embedding_model: str = "models/gemini-embedding-001"
    embedding_dimensions: int = Field(default=768, ge=1, le=4096)
    openai_api_key: SecretStr = SecretStr("")
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection: str = "smartrag_google_768_v1"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "smartrag"
    s3_secret_key: SecretStr
    s3_bucket: str = "smartrag-documents"
    s3_region: str = "us-east-1"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_pdf_pages: int = Field(default=1000, ge=1, le=5000)
    parser_engine: Literal["docling", "pymupdf"] = "docling"
    docling_artifacts_path: str | None = None
    extraction_mode: Literal["auto", "text-first", "ocr-enabled", "enhanced-multimodal"] = "auto"
    ocr_backend: Literal["tesseract", "disabled"] = "tesseract"
    ocr_language: str = "eng"
    tesseract_cmd: str = "tesseract"
    ocr_timeout_seconds: int = Field(default=60, ge=1, le=300)
    render_max_dimension: int = Field(default=1800, ge=256, le=3000)
    render_dpi: int = Field(default=150, ge=72, le=300)
    max_figures_per_page: int = Field(default=8, ge=0, le=30)
    vision_enabled: bool = False
    vision_model: str = "gemini-3.8-flash"
    max_vision_calls: int = Field(default=6, ge=0, le=50)
    chunk_tokens: int = Field(default=450, ge=100, le=2000)
    chunk_overlap_tokens: int = Field(default=50, ge=0, le=99)
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    embedding_version: str = "v1"
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ingestion_timeout_seconds: int = Field(default=3600, ge=30, le=14400)
    ingestion_max_attempts: int = Field(default=3, ge=1, le=10)
    page_timeout_seconds: int = Field(default=180, ge=10, le=600)
    max_extracted_characters: int = Field(default=20_000_000, ge=1000)

    @model_validator(mode="after")
    def secure_configuration(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or "CHANGE_ME" in secret:
            raise ValueError("JWT_SECRET must be a unique random secret of at least 32 characters")
        if "CHANGE_ME" in self.s3_secret_key.get_secret_value():
            raise ValueError("Configure S3_SECRET_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
