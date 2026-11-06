"""Measure synthetic page-bounded extraction and chunking, without embeddings or vision."""

import argparse
import json
import tempfile
import threading
import time
from pathlib import Path

import psutil

from backend.app.core.config import get_settings
from backend.app.rag.extraction import extract_pages
from backend.app.rag.types import structured_chunks
from scripts.pdf_fixtures import synthetic_pdf


def main() -> None:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--pages", type=int, default=520)
    arguments.add_argument("--engine", choices=["pymupdf", "docling"], default="pymupdf")
    args = arguments.parse_args()
    settings = get_settings().model_copy(
        update={"parser_engine": args.engine, "max_pdf_pages": max(1000, args.pages)}
    )
    process = psutil.Process()
    peak = process.memory_info().rss
    stopped = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not stopped.wait(0.02):
            peak = max(peak, process.memory_info().rss)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    count = chunks = tables = figures = 0
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="smartrag-benchmark-") as directory:
            source = Path(directory) / "synthetic.pdf"
            source.write_bytes(synthetic_pdf(pages=args.pages))
            for result in extract_pages(source, settings, "text-first"):
                count += 1
                chunks += len(structured_chunks(result.elements, settings))
                tables += sum(element.kind == "table" for element in result.elements)
                figures += sum(element.kind == "figure" for element in result.elements)
        print(
            json.dumps(
                {
                    "fixture": "synthetic",
                    "engine": args.engine,
                    "pages": count,
                    "chunks": chunks,
                    "tables": tables,
                    "figures": figures,
                    "seconds": round(time.monotonic() - started, 3),
                    "peak_process_rss_mib": round(peak / 1024**2, 2),
                    "scope": "fixture generation + extraction + chunking; no embeddings or vision",
                }
            )
        )
    finally:
        stopped.set()
        monitor.join()


if __name__ == "__main__":
    main()
