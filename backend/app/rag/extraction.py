"""Page-bounded PDF inspection, structural extraction, selective OCR and secure assets."""

import base64
import hashlib
import io
import re
import shutil
import time
import zlib
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
import pytesseract
from PIL import Image
from pypdf import PdfReader

from backend.app.core.config import Settings
from backend.app.core.telemetry import observed, operation
from backend.app.rag.types import Element
from backend.app.security.content import inspect_content


class InvalidDocument(ValueError):
    pass


class ProcessingCancelled(Exception):
    pass


class ProcessingDependencyError(Exception):
    pass


@dataclass
class PageResult:
    page: int
    elements: list[Element]
    quality: dict[str, Any]
    strategy: str
    warnings: list[str]


def text_quality(text: str) -> dict[str, Any]:
    compact = text.strip()
    printable = sum(character.isprintable() or character.isspace() for character in compact)
    usable = len(compact) >= 30 and printable / max(1, len(compact)) >= 0.95
    usable = usable and compact.count("\ufffd") / max(1, len(compact)) < 0.02
    return {
        "usable_text": usable,
        "characters": len(compact),
        "replacement_characters": compact.count("\ufffd"),
    }


def render_page(page: Any, settings: Settings, clip: Any = None) -> bytes:
    rect = clip or page.rect
    scale = min(
        settings.render_dpi / 72, settings.render_max_dimension / max(rect.width, rect.height)
    )
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), clip=clip, colorspace=pymupdf.csRGB, alpha=False
    )
    return bytes(pixmap.tobytes("png"))


@observed("ingestion.ocr")
def ocr_image(data: bytes, settings: Settings) -> tuple[str, dict[str, Any]]:
    if settings.ocr_backend == "disabled":
        raise ProcessingDependencyError("OCR is disabled; enable Tesseract for scanned pages")
    if not shutil.which(settings.tesseract_cmd) and not Path(settings.tesseract_cmd).is_file():
        raise ProcessingDependencyError("Install Tesseract and configure TESSERACT_CMD")
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        with Image.open(io.BytesIO(data)) as image:
            result = pytesseract.image_to_data(
                image,
                lang=settings.ocr_language,
                timeout=settings.ocr_timeout_seconds,
                output_type=pytesseract.Output.DICT,
            )
        lines: dict[tuple[int, int, int], list[str]] = {}
        confidences: list[float] = []
        for index, word in enumerate(result["text"]):
            if not word.strip():
                continue
            key = (result["block_num"][index], result["par_num"][index], result["line_num"][index])
            lines.setdefault(key, []).append(word)
            value = float(result["conf"][index])
            if value >= 0:
                confidences.append(value)
        text = "\n".join(" ".join(words) for words in lines.values())
        # Tesseract word confidence is reported as supplied, not a calibrated accuracy estimate.
        quality: dict[str, Any] = {"ocr_engine": "tesseract", "ocr_word_count": len(confidences)}
        if confidences:
            quality["ocr_mean_word_confidence"] = sum(confidences) / len(confidences)
        return text, quality
    except Exception as exc:
        raise ProcessingDependencyError("OCR failed or timed out; verify language packs") from exc


class DoclingParser:
    def __init__(self, settings: Settings) -> None:
        self.converters: dict[bool, Any] = {}
        self.settings = settings

    def parse(self, source: Path, page_number: int, use_ocr: bool = False) -> list[Element]:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        if use_ocr not in self.converters:
            options = PdfPipelineOptions(do_ocr=use_ocr, do_table_structure=True)
            if use_ocr:
                options.ocr_options = TesseractCliOcrOptions(
                    mode="full_page",
                    lang=self.settings.ocr_language.split("+"),
                    tesseract_cmd=self.settings.tesseract_cmd,
                )
            options.generate_page_images = False
            options.generate_picture_images = False
            options.document_timeout = self.settings.page_timeout_seconds
            if self.settings.docling_artifacts_path:
                options.artifacts_path = Path(self.settings.docling_artifacts_path)
            self.converters[use_ocr] = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
        # Only one page enters the model pipeline at a time; the converter/model is reused.
        result = self.converters[use_ocr].convert(source, page_range=(page_number, page_number))
        document = result.document
        elements: list[Element] = []
        heading = ""
        for item, _level in document.iterate_items():
            label = str(getattr(item, "label", "")).split(".")[-1].lower()
            text = getattr(item, "text", "") or ""
            identifier = f"page-{page_number}-{len(elements)}"
            if label in {"page_header", "page_footer"}:
                continue
            if label in {"section_header", "title"}:
                heading = text
            if label == "table":
                grid = item.data.grid
                rows = [[cell.text for cell in row] for row in grid]
                headers, body, header_rows = table_headers(rows)
                caption = item.caption_text(document) or f"Table {len(elements) + 1}"
                data = {
                    "headers": headers,
                    "rows": body,
                    "header_rows": header_rows,
                    "cells": item.data.model_dump(mode="json"),
                    "caption": caption,
                }
                elements.append(
                    Element(page_number, "table", caption, identifier, "docling", heading, data)
                )
            elif text.strip():
                kind = "formula" if label == "formula" else "text"
                elements.append(Element(page_number, kind, text, identifier, "docling", heading))
        return elements


def table_headers(rows: list[list[Any]]) -> tuple[list[Any], list[list[Any]], list[list[Any]]]:
    if not rows:
        return [], [], []
    nonempty = {str(value) for value in rows[0] if value}
    if len(nonempty) == 1 and len(rows) > 1 and len(rows[0]) > 1:
        group = next(iter(nonempty))
        return [f"{group} / {value or ''}" for value in rows[1]], rows[2:], rows[:2]
    return rows[0], rows[1:], rows[:1]


def _furniture(document: Any) -> set[str]:
    count: Counter[str] = Counter()
    samples = min(12, len(document))
    if samples < 3:
        return set()
    for number in range(samples):
        page = document[number]
        seen = set()
        for block in page.get_text("blocks"):
            if block[1] < 55 or block[3] > page.rect.height - 45:
                seen.add(re.sub(r"\d+", "#", str(block[4]).strip()))
        count.update(seen)
    return {text for text, occurrences in count.items() if occurrences >= max(3, samples * 0.6)}


def _fallback(page: Any, number: int, furniture: set[str]) -> list[Element]:
    elements: list[Element] = []
    table_rects: list[Any] = []
    try:
        for ordinal, table in enumerate(page.find_tables().tables):
            rows = table.extract()
            if len(rows) < 2:
                continue
            table_rects.append(pymupdf.Rect(table.bbox))
            headers, body, header_rows = table_headers(rows)
            above = page.get_textbox(
                pymupdf.Rect(
                    table.bbox[0], max(0, table.bbox[1] - 55), table.bbox[2], table.bbox[1]
                )
            ).strip()
            caption = next(
                (line for line in above.splitlines() if re.match(r"\s*table\s+\d+", line, re.I)),
                f"Table {ordinal + 1}",
            )
            elements.append(
                Element(
                    number,
                    "table",
                    caption,
                    f"page-{number}-table-{ordinal}",
                    "pymupdf",
                    data={
                        "headers": headers,
                        "rows": body,
                        "header_rows": header_rows,
                        "bbox": list(table.bbox),
                        "cells": table.cells,
                    },
                )
            )
    except Exception:
        pass  # Explicit fallback warning is added by the caller; text remains available.
    blocks = [block for block in page.get_text("blocks", sort=True) if block[6] == 0]
    # Read columns as columns if both have text and no body block spans the gutter.
    body = [block for block in blocks if block[1] > 65 and block[3] < page.rect.height - 50]
    midpoint = page.rect.width / 2
    if (
        any(block[2] < midpoint for block in body)
        and any(block[0] > midpoint for block in body)
        and not any(block[0] < midpoint - 20 < block[2] for block in body)
    ):
        blocks = sorted(blocks, key=lambda block: (block[0] >= midpoint, block[1]))
    heading = ""
    for ordinal, block in enumerate(blocks):
        text = str(block[4]).strip()
        if re.sub(r"\d+", "#", text) in furniture:
            continue
        rect = pymupdf.Rect(block[:4])
        if any(rect.intersects(table_rect) for table_rect in table_rects):
            continue
        if not text:
            continue
        if len(text) < 100 and "\n" not in text and (text.isupper() or re.match(r"^\d+[. ]", text)):
            heading = text
        elements.append(
            Element(number, "text", text, f"page-{number}-text-{ordinal}", "pymupdf", heading)
        )
    return elements


AssetSink = Callable[[int, str, bytes, str, dict[str, Any]], str]
Vision = Callable[[bytes, str], str]


@observed("ingestion.inspect")
def inspect_pdf(source: Path, settings: Settings) -> int:
    try:
        # Reject malformed cross references before MuPDF's repair path can retain an
        # invalid file handle on Windows and obstruct temporary-file cleanup.
        with source.open("rb") as stream:
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                raise InvalidDocument("Encrypted PDFs are unsupported")
            if not 1 <= len(reader.pages) <= settings.max_pdf_pages:
                raise InvalidDocument(f"PDF must have 1 to {settings.max_pdf_pages} pages")
        with pymupdf.open(source) as document:
            if document.needs_pass:
                raise InvalidDocument("Encrypted PDFs are unsupported")
            if not 1 <= len(document) <= settings.max_pdf_pages:
                raise InvalidDocument(f"PDF must have 1 to {settings.max_pdf_pages} pages")
            if document.xref_length() > settings.max_pdf_objects or document.embfile_count():
                raise InvalidDocument("PDF object count or embedded attachments are unsupported")
            decoded_total = 0
            for xref in range(1, document.xref_length()):
                obj = document.xref_object(xref, compressed=False)
                if re.search(
                    r"/(?:JavaScript|JS|Launch|OpenAction|AA|XFA|RichMedia|EmbeddedFiles)\b", obj
                ):
                    raise InvalidDocument("Active PDF content is unsupported")
                if not document.xref_is_stream(xref):
                    continue
                raw = document.xref_stream_raw(xref)
                if not raw:
                    continue
                # Bound expansion before MuPDF/Docling decodes Flate streams.
                if re.search(r"/FlateDecode\b", obj):
                    if re.search(r"/ASCII85Decode\b", obj):
                        raw = base64.a85decode(raw.strip().removesuffix(b"~>"))
                    decoder = zlib.decompressobj()
                    limit = min(
                        settings.max_pdf_stream_bytes - decoded_total,
                        len(raw) * settings.max_pdf_expansion_ratio,
                    )
                    decoded = decoder.decompress(raw, limit + 1)
                    if len(decoded) > limit or decoder.unconsumed_tail:
                        raise InvalidDocument("PDF stream expansion limit exceeded")
                    decoded_total += len(decoded)
                else:
                    decoded_total += len(raw)
                if decoded_total > settings.max_pdf_stream_bytes:
                    raise InvalidDocument("PDF stream budget exceeded")
            for page in document:
                for image in page.get_images(full=True):
                    if image[2] * image[3] > settings.max_pdf_image_pixels:
                        raise InvalidDocument("PDF image pixel budget exceeded")
            return len(document)
    except InvalidDocument:
        raise
    except Exception as exc:
        raise InvalidDocument("Malformed or unsupported PDF") from exc


def _extract_pages(
    source: Path,
    settings: Settings,
    mode: str,
    asset_sink: AssetSink | None = None,
    vision: Vision | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> Iterator[PageResult]:
    inspect_pdf(source, settings)
    parser = DoclingParser(settings) if settings.parser_engine == "docling" else None
    vision_calls = 0
    characters = 0
    started = time.monotonic()
    with pymupdf.open(source) as document:
        furniture = _furniture(document)
        for ordinal in range(len(document)):
            if checkpoint:
                checkpoint()
            if time.monotonic() - started > settings.ingestion_timeout_seconds:
                raise ProcessingDependencyError("Document processing deadline exceeded")
            page = document[ordinal]
            number = ordinal + 1
            if asset_sink:
                preview_settings = settings.model_copy(
                    update={"render_max_dimension": 900, "render_dpi": 96}
                )
                asset_sink(
                    number,
                    "page_preview",
                    render_page(page, preview_settings),
                    "",
                    {"extension": "png"},
                )
            raw = page.get_text("text", sort=True)
            quality = text_quality(raw)
            inspection = inspect_content(raw, settings.security_block_threshold)
            quality["raw_security"] = inspection.as_dict()
            if inspection.decision == "block":
                yield PageResult(
                    number,
                    [],
                    quality,
                    "security-quarantine",
                    ["Page quarantined by content security policy"],
                )
                continue
            images = page.get_images(full=True)
            quality["content_type"] = (
                "mixed"
                if images and quality["usable_text"]
                else ("text" if quality["usable_text"] else "scan-or-unreadable")
            )
            warnings: list[str] = []
            elements: list[Element] = []
            needs_ocr = not quality["usable_text"] or mode == "ocr-enabled"
            docling_ocr = False
            if parser:
                try:
                    use_ocr = (
                        needs_ocr and mode != "text-first" and settings.ocr_backend != "disabled"
                    )
                    elements = parser.parse(source, number, use_ocr=use_ocr)
                    docling_ocr = (
                        use_ocr and text_quality(" ".join(e.text for e in elements))["usable_text"]
                    )
                except Exception:
                    warnings.append(
                        "Docling unavailable or page parse failed; PyMuPDF fallback used"
                    )
            if not elements:
                elements = _fallback(page, number, furniture)
            strategy = "docling" if any(e.method == "docling" for e in elements) else "pymupdf"
            if docling_ocr:
                strategy = "docling-ocr"
                quality.update(text_quality(" ".join(element.text for element in elements)))
                quality["ocr_engine"] = "docling-tesseract"
                for element in elements:
                    element.method = "docling-tesseract"
            elif needs_ocr and mode != "text-first":
                text, indicators = ocr_image(render_page(page, settings), settings)
                quality.update(indicators)
                quality.update(text_quality(text))
                if text.strip():
                    # Full-page OCR replaces bad embedded text rather than duplicating it.
                    elements = [element for element in elements if element.kind == "table"]
                    elements.append(
                        Element(number, "text", text, f"page-{number}-ocr", "tesseract")
                    )
                    strategy = "tesseract"
            if not quality["usable_text"]:
                warnings.append("Page text quality is low; extraction may omit information")
            caption_candidates = [
                line
                for line in raw.splitlines()
                if re.match(r"\s*(fig(?:ure)?[. ]|chart|diagram)", line, re.I)
            ]
            caption = "\n".join(caption_candidates)[:1500]
            # Embedded images are bounded via page rendering of their rectangle, not decoded at
            # their original potentially huge resolution. Vector-only figures get a page asset.
            regions: list[Any] = []
            for image in images[: settings.max_figures_per_page]:
                if asset_sink and image[2] * image[3] <= 16_000_000:
                    try:
                        original = document.extract_image(image[0])
                        asset_sink(
                            number,
                            "original",
                            original["image"],
                            caption,
                            {
                                "extension": original["ext"],
                                "width": image[2],
                                "height": image[3],
                                "original_image_stream": True,
                            },
                        )
                    except Exception:
                        warnings.append(
                            "Original image extraction unavailable; rendered source retained"
                        )
                elif asset_sink:
                    warnings.append(
                        "Oversized original image remains in PDF; bounded preview retained"
                    )
                rectangles = page.get_image_rects(image[0])
                if rectangles:
                    rect = rectangles[0] & page.rect
                    if rect.width >= 40 and rect.height >= 40:
                        regions.append(rect)
            if not regions and (
                caption
                or (len(page.get_drawings()) > 10 and not any(e.kind == "table" for e in elements))
            ):
                regions = [page.rect]
            for index, region in enumerate(regions[: settings.max_figures_per_page]):
                data = render_page(page, settings, region)
                details = {"bbox": list(region), "sha256": hashlib.sha256(data).hexdigest()}
                asset = asset_sink(number, "figure", data, caption, details) if asset_sink else None
                text = caption or f"Figure on page {number}; visual interpretation unavailable."
                method = "pymupdf-figure"
                derived = False
                if mode != "text-first" and quality.get("content_type") == "mixed":
                    try:
                        figure_text, _indicators = ocr_image(data, settings)
                        if figure_text.strip():
                            text += (
                                "\nOCR labels from figure (not a visual interpretation): "
                                + figure_text
                            )
                            method = "tesseract-figure"
                    except ProcessingDependencyError:
                        warnings.append(
                            "Figure label OCR unavailable; source image and caption retained"
                        )
                if mode == "enhanced-multimodal" and settings.vision_enabled and vision:
                    if vision_calls < settings.max_vision_calls:
                        vision_calls += 1
                        try:
                            text += "\nModel-derived visual description: " + vision(data, caption)
                            method, derived = "gemini-vision", True
                        except Exception:
                            warnings.append("Vision provider failed; figure and caption retained")
                    else:
                        warnings.append(
                            "Vision call budget reached; remaining figures use captions"
                        )
                elements.append(
                    Element(
                        number,
                        "figure",
                        text,
                        f"page-{number}-figure-{index}",
                        method,
                        data=details,
                        asset_id=asset,
                        model_derived=derived,
                    )
                )
            if mode == "enhanced-multimodal" and not settings.vision_enabled:
                warnings.append("Vision disabled; no model-derived image understanding performed")
            characters += sum(len(element.text) + len(str(element.data)) for element in elements)
            if characters > settings.max_extracted_characters:
                raise InvalidDocument("Extracted content exceeds configured safety limit")
            if not elements:
                warnings.append("No readable content found on this page")
            yield PageResult(number, elements, quality, strategy, warnings)


def extract_pages(
    source: Path,
    settings: Settings,
    mode: str,
    asset_sink: AssetSink | None = None,
    vision: Vision | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> Iterator[PageResult]:
    with operation("ingestion.extract"):
        yield from _extract_pages(source, settings, mode, asset_sink, vision, checkpoint)
