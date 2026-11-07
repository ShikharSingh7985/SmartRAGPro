"""Content fingerprint of public application source; never includes environment files."""

import hashlib
import tomllib
from functools import lru_cache
from pathlib import Path


@lru_cache
def build_info() -> dict[str, str]:
    digest = hashlib.sha256()
    for root in [Path("backend"), Path("frontend")]:
        for path in sorted(root.rglob("*.py")):
            digest.update(path.as_posix().encode())
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    project = Path("pyproject.toml")
    version = tomllib.loads(project.read_text())["project"]["version"]
    return {"version": version, "source_sha256": digest.hexdigest()}
