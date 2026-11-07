"""Normalize grouped numeric citations before the existing scope verification."""

import re

REFERENCE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def normalize_citations(text: str) -> str:
    return REFERENCE.sub(
        lambda match: "".join(f"[{int(number.strip())}]" for number in match[1].split(",")),
        text,
    )


def strip_citations(text: str) -> str:
    return REFERENCE.sub("", text)
