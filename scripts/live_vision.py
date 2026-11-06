"""Explicit live, potentially paid vision probe. Never part of deterministic pytest."""

import argparse
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.services.resources import GeminiGenerator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.vision_enabled:
        raise SystemExit("Set VISION_ENABLED=true locally to authorize optional live vision calls")
    import io

    from PIL import Image

    with Image.open(args.image) as source:
        source.thumbnail((settings.render_max_dimension, settings.render_max_dimension))
        buffer = io.BytesIO()
        source.convert("RGB").save(buffer, format="PNG")
    try:
        model = GeminiGenerator(settings.model_copy(update={"gemini_model": settings.vision_model}))
        description = model.describe(
            buffer.getvalue(), "Synthetic public visual acceptance fixture"
        )
        # Do not print private source content; this probe verifies nonempty live output only.
        if not description.strip():
            raise RuntimeError("Empty description")
        print(
            "LIVE vision returned a nonempty model-derived description. "
            "Human fidelity review still required."
        )
    except Exception:
        raise SystemExit(
            "Live vision unavailable; check local provider configuration and quota"
        ) from None


if __name__ == "__main__":
    main()
