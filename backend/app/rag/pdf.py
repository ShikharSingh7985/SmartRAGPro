from dataclasses import dataclass
from io import BytesIO

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


@dataclass(frozen=True)
class Chunk:
    page: int
    text: str


def extract_chunks(data: bytes, max_pages: int = 300) -> tuple[int, list[Chunk]]:
    if not data.startswith(b"%PDF-"):
        raise ValueError("Upload must be a valid PDF")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are unsupported")
        count = len(reader.pages)
        if not 1 <= count <= max_pages:
            raise ValueError(f"PDF must have 1 to {max_pages} pages")
        splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=180)
        chunks: list[Chunk] = []
        total = 0
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            total += len(text)
            if total > 2_000_000:
                raise ValueError("PDF exceeds extracted text limit")
            chunks.extend(Chunk(number, part) for part in splitter.split_text(text) if part.strip())
        if not chunks:
            raise ValueError("No digital text found; OCR is not supported in Phase 1")
        return count, chunks
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Malformed or unsupported PDF") from exc
