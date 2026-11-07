"""Scan index bytes before committing; --all scans tracked working-tree source in CI."""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "Google API key": rb"AIza[0-9A-Za-z_-]{35}",
    "GitHub token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    "OpenAI key": rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
    "AWS access key": rb"AKIA[0-9A-Z]{16}",
}


def main() -> None:
    all_files = "--all" in sys.argv
    args = (
        ["git", "ls-files", "-z"]
        if all_files
        else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    )
    paths = subprocess.check_output(args).decode().split("\0")
    failures: list[str] = []
    for name in filter(None, paths):
        path = Path(name)
        if path.name.startswith(".env") and path.name != ".env.example":
            failures.append(f"{name}: environment secrets file")
        if path.suffix.lower() in {
            ".pdf",
            ".db",
            ".sqlite",
            ".pem",
            ".key",
            ".exe",
            ".zip",
            ".dump",
        }:
            failures.append(f"{name}: forbidden private/generated artifact")
        data = (
            path.read_bytes() if all_files else subprocess.check_output(["git", "show", f":{name}"])
        )
        if len(data) > 1_000_000 or b"\0" in data:
            failures.append(f"{name}: unexpected binary or oversized file")
        for rule, pattern in PATTERNS.items():
            if re.search(pattern, data):
                failures.append(f"{name}: potential {rule}")
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"Secret/artifact scan passed for {len(list(filter(None, paths)))} files")


if __name__ == "__main__":
    main()
