"""Explicit synthetic acceptance over real HTTP, real workers, storage and embeddings."""

import argparse
import secrets
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdfs", type=Path, nargs="+")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    credentials = {
        "email": f"synthetic-{uuid4().hex}@example.com",
        "password": secrets.token_urlsafe(36),
    }
    documents: list[str] = []
    # Polling pauses may cross the server's keepalive expiry; use fresh connections.
    limits = httpx.Limits(max_keepalive_connections=0)
    with httpx.Client(base_url=args.api, timeout=120, limits=limits) as client:
        registration = client.post("/api/v1/auth/register", json=credentials)
        registration.raise_for_status()
        login = client.post("/api/v1/auth/login", json=credentials)
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        try:
            for source in args.pdfs:
                started = time.monotonic()
                with source.open("rb") as stream:
                    response = client.post(
                        "/api/v1/documents",
                        files={"file": (source.name, stream, "application/pdf")},
                        data={"extraction_mode": "auto"},
                    )
                response.raise_for_status()
                identifier = response.json()["id"]
                documents.append(identifier)
                while time.monotonic() - started < args.timeout:
                    response = client.get(f"/api/v1/documents/{identifier}")
                    response.raise_for_status()
                    document = response.json()
                    if document["status"] == "ready":
                        print(
                            {
                                "synthetic_fixture": source.name,
                                "status": "ready",
                                "pages": document["page_count"],
                                "chunks": document["chunk_count"],
                                "tables": document["table_count"],
                                "figures": document["figure_count"],
                                "seconds": round(time.monotonic() - started, 2),
                            },
                            flush=True,
                        )
                        break
                    if document["status"] == "failed":
                        raise RuntimeError("Live ingestion failed; check sanitized job status")
                    time.sleep(5)
                else:
                    raise RuntimeError("Live ingestion timed out")
        finally:
            for identifier in documents:
                client.delete(f"/api/v1/documents/{identifier}")
            client.post("/api/v1/auth/logout")
    print("Synthetic source documents queued for deletion; synthetic account metadata remains.")


if __name__ == "__main__":
    main()
