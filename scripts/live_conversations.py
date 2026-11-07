"""Explicit paid-capable HTTP acceptance using a synthetic ML PDF and real providers."""

import argparse
import json
import secrets
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.textbook_fixture import textbook_pdf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--restart-api", action="store_true")
    args = parser.parse_args()
    observations = []
    status = "failed"
    credentials = {
        "email": f"synthetic-chat-{uuid4().hex}@example.com",
        "password": secrets.token_urlsafe(36),
    }
    document_id = conversation_id = None
    account_cleanup_queued = False
    expected_method = None
    stage = "registration"
    client = httpx.Client(base_url="http://localhost:8000", timeout=240)
    runtime = client.get("/health/live").json()
    try:
        client.post("/api/v1/auth/register", json=credentials).raise_for_status()
        token = client.post("/api/v1/auth/login", json=credentials)
        token.raise_for_status()
        client.headers["Authorization"] = "Bearer " + token.json()["access_token"]
        stage = "synthetic PDF ingestion"
        ingestion_started = time.monotonic()
        result = client.post(
            "/api/v1/documents",
            files={"file": ("synthetic-ml.pdf", textbook_pdf(), "application/pdf")},
            data={"extraction_mode": "text-first"},
        )
        result.raise_for_status()
        document_id = result.json()["id"]
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/documents/{document_id}")
            response.raise_for_status()
            if response.json()["status"] == "ready":
                break
            if response.json()["status"] == "failed":
                raise RuntimeError("Ingestion failed")
            time.sleep(3)
        else:
            raise RuntimeError("Ingestion timed out")
        observations.append(
            {
                "stage": "full_ingestion",
                "seconds": time.monotonic() - ingestion_started,
                "pages": 4,
                "scope": "HTTP upload, storage, worker, embeddings, SQL/vector publication",
            }
        )
        result = client.post("/api/v1/conversations", json={"document_ids": [document_id]})
        result.raise_for_status()
        conversation_id = result.json()["id"]
        questions = [
            "What is overfitting?",
            "How can I overcome it?",
            "Which of those techniques is explained in chapter 5?",
            "Can you explain the second method with an example?",
        ]
        for turn, question in enumerate(questions, 1):
            if turn == 3:
                stage = "fresh-client login and history restoration"
                client.post("/api/v1/auth/logout").raise_for_status()
                client.close()
                if args.restart_api:
                    restarted = subprocess.run(
                        ["docker", "compose", "restart", "api"], capture_output=True
                    )
                    if restarted.returncode:
                        raise RuntimeError("API restart failed")
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        try:
                            if (
                                httpx.get(
                                    "http://localhost:8000/health/ready", timeout=5
                                ).status_code
                                == 200
                            ):
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(2)
                    else:
                        raise RuntimeError("API readiness after restart timed out")
                client = httpx.Client(base_url="http://localhost:8000", timeout=240)
                login = client.post("/api/v1/auth/login", json=credentials)
                login.raise_for_status()
                client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
                restored = client.get(f"/api/v1/conversations/{conversation_id}/messages")
                restored.raise_for_status()
                assert len(restored.json()) == 4
            stage = f"Gemini conversational turn {turn}"
            start = time.monotonic()
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": question, "request_id": str(uuid4())},
            )
            response.raise_for_status()
            reply = response.json()
            # This script creates only public synthetic text; retain outputs for honest
            # regression diagnosis, never reuse this export path for private documents.
            observations.append(
                {
                    "stage": "synthetic_reply",
                    "turn": turn,
                    "content": reply["content"],
                    "citation_count": len(reply["citations"]),
                }
            )
            if turn == 3:
                text = reply["content"].casefold()
                order = sorted(
                    (text.find(name), name) for name in ["regularization", "early stopping"]
                )
                assert all(index >= 0 for index, _ in order), "Expected fixture methods missing"
                expected_method = order[1][1]
            if turn == 4:
                assert expected_method in reply["content"].casefold(), "Wrong ordinal reference"
                observations[-1]["expected_method"] = expected_method
            assert reply["citations"], "No grounded source references"
            assert all(
                c["document_id"] == document_id and 1 <= c["page"] <= 4 for c in reply["citations"]
            )
            if turn >= 3:
                assert {citation["page"] for citation in reply["citations"]} == {3}
            observations.append(
                {
                    "stage": "whole_turn",
                    "turn": turn,
                    "seconds": time.monotonic() - start,
                    "source_pages": sorted({c["page"] for c in reply["citations"]}),
                }
            )
            print(
                {
                    "turn": turn,
                    "seconds": round(time.monotonic() - start, 3),
                    "source_pages": sorted({c["page"] for c in reply["citations"]}),
                },
                flush=True,
            )
        print("LIVE four-turn conversation and fresh-client restoration passed")
        status = "passed"
    except httpx.HTTPStatusError as exc:
        raise SystemExit(
            f"LIVE check failed at {stage}: HTTP {exc.response.status_code}; details suppressed"
        ) from None
    except Exception:
        raise SystemExit(f"LIVE check failed at {stage}; details suppressed") from None
    finally:
        for resource, identifier in [
            ("documents", document_id),
            ("conversations", conversation_id),
        ]:
            if identifier:
                try:
                    client.delete(f"/api/v1/{resource}/{identifier}")
                except httpx.HTTPError:
                    pass
        try:
            cleanup = client.request(
                "DELETE", "/api/v1/auth/account", json={"password": credentials["password"]}
            )
            account_cleanup_queued = cleanup.status_code == 202
        except httpx.HTTPError:
            pass
        client.close()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    {
                        "status": status,
                        "runtime": runtime,
                        "last_stage": stage,
                        "synthetic": True,
                        "api_restart_requested": args.restart_api,
                        "account_cleanup_queued": account_cleanup_queued,
                        "observations": observations,
                    },
                    indent=2,
                )
            )
        print("Synthetic source cleanup requested; account cleanup queued:", account_cleanup_queued)


if __name__ == "__main__":
    main()
