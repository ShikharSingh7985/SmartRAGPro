"""Mirror public synthetic page labels into actual PDFs and time bounded extraction."""

import json
import textwrap
from pathlib import Path
from time import perf_counter

import psutil
from reportlab.pdfgen.canvas import Canvas

from backend.app.core.config import get_settings
from backend.app.rag.extraction import extract_pages
from backend.app.rag.types import structured_chunks
from evaluation.dataset import load


def main():
    dataset = load()
    folder = Path("evaluation/.cache/pdfs")
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for identifier in sorted({c.document_id for c in dataset.chunks}):
        path = folder / (identifier + ".pdf")
        canvas = Canvas(str(path))
        for chunk in [c for c in dataset.chunks if c.document_id == identifier]:
            text = canvas.beginText(60, 760)
            for line in textwrap.wrap(
                chunk.text, 85, break_long_words=False, break_on_hyphens=False
            ):
                text.textLine(line)
            canvas.drawText(text)
            if chunk.content_type == "figure":
                canvas.lines([(80, 200, 180, 350), (180, 350, 280, 240)])
                canvas.drawString(80, 180, "1")
                canvas.drawString(180, 180, "2 (peak)")
                canvas.drawString(280, 180, "3")
            if chunk.content_type == "table":
                canvas.grid([60, 210, 360, 510], [500, 530, 560])
                canvas.drawString(70, 540, "Approach")
                canvas.drawString(220, 540, "Accuracy percent")
                canvas.drawString(370, 540, "Training hours")
            canvas.showPage()
        canvas.save()
        paths.append(path)
    settings = get_settings().model_copy(update={"parser_engine": "pymupdf"})
    samples = []
    process = psutil.Process()
    for repeat in range(3):
        pages = chunks = characters = 0
        started = perf_counter()
        for path in paths:
            for page in extract_pages(path, settings, "text-first"):
                pages += 1
                chunks += len(structured_chunks(page.elements, settings))
                characters += sum(len(element.text) for element in page.elements)
        seconds = perf_counter() - started
        samples.append(
            {
                "repeat": repeat,
                "pages": pages,
                "chunks": chunks,
                "characters": characters,
                "seconds": seconds,
                "pages_per_second": pages / seconds,
                "final_rss_bytes": process.memory_info().rss,
            }
        )
    Path("evaluation/results/ingestion.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "scope": "actual PDFs, PyMuPDF extraction and chunking; "
                "excludes OCR, embeddings and queue/storage",
                "results": samples,
            },
            indent=2,
        )
    )
    print(json.dumps(samples))


if __name__ == "__main__":
    main()
