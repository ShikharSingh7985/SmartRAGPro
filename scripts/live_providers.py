"""Explicit paid-capable provider probe. Requires real locally configured keys."""

from backend.app.services.resources import get_resources


def main() -> None:
    resources = get_resources()
    try:
        text = "The synthetic evaluation document reports revenue of 42 million dollars."
        vectors = resources.embedding.embed_documents([text])
        query = resources.embedding.embed_query("What revenue is reported?")
        if len(vectors) != 1 or len(vectors[0]) != resources.settings.embedding_dimensions:
            raise RuntimeError("Unexpected document embedding dimensions")
        if len(query) != resources.settings.embedding_dimensions:
            raise RuntimeError("Unexpected query embedding dimensions")
        result = resources.generator.answer(
            "What revenue is reported?", f"[1] probe.pdf, page 1: {text}"
        )
        if "42" not in result or "[1]" not in result:
            raise RuntimeError("Live answer did not satisfy basic grounding probe")
        print("LIVE provider probe passed: real embeddings and real Gemini cited answer")
    except Exception:
        raise SystemExit(
            "Live provider probe failed. Check local credentials/model/quota; details suppressed."
        ) from None
    finally:
        resources.close()


if __name__ == "__main__":
    main()
