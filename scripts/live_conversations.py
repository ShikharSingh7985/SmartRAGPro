"""Explicit paid-capable HTTP acceptance using a synthetic ML PDF and real providers."""

import secrets
import time
from uuid import uuid4

import httpx

from scripts.textbook_fixture import textbook_pdf


def main() -> None:
    credentials = {
        "email": f"synthetic-chat-{uuid4().hex}@example.com",
        "password": secrets.token_urlsafe(36),
    }
    document_id = conversation_id = None
    stage = "registration"
    client = httpx.Client(base_url="http://localhost:8000", timeout=240)
    try:
        client.post("/api/v1/auth/register", json=credentials).raise_for_status()
        token = client.post("/api/v1/auth/login", json=credentials)
        token.raise_for_status()
        client.headers["Authorization"] = "Bearer " + token.json()["access_token"]
        stage = "synthetic PDF ingestion"
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
            assert reply["citations"], "No grounded source references"
            assert all(
                c["document_id"] == document_id and 1 <= c["page"] <= 4 for c in reply["citations"]
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
            client.post("/api/v1/auth/logout")
        except httpx.HTTPError:
            pass
        client.close()
        print("Synthetic source cleanup requested; synthetic account metadata remains.")


if __name__ == "__main__":
    main()
