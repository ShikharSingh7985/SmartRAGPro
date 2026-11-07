"""Binary-safe Compose PostgreSQL backup/restore; dumps always stay ignored and private."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args: list[str]) -> None:
    completed = subprocess.run(args, capture_output=True, check=False)
    if completed.returncode:
        raise SystemExit("Database backup operation failed; private subprocess details suppressed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose", default="docker-compose.yml")
    parser.add_argument("--database", choices=["smartrag", "smartrag_test"], required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--confirm-disposable", action="store_true")
    args = parser.parse_args()
    base = ["docker", "compose", "-p", args.project, "-f", args.compose]
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dump = directory / "postgres.dump"
    manifest = directory / "manifest.json"
    if args.action == "backup":
        if dump.exists():
            raise SystemExit("Use a new backup directory; existing backup preserved")
        run(
            [
                *base,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "smartrag",
                "-d",
                args.database,
                "-Fc",
                "-f",
                "/tmp/smartrag-backup.dump",
            ]
        )
        run([*base, "cp", "postgres:/tmp/smartrag-backup.dump", str(dump)])
        manifest.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(UTC).isoformat(),
                    "database": args.database,
                    "sha256": checksum(dump),
                    "scope": "PostgreSQL only. S3 originals and vector backups are separate.",
                    "encryption": (
                        "NOT encrypted; protect locally and encrypt before off-host transfer."
                    ),
                },
                indent=2,
            )
            + "\n"
        )
    else:
        if args.database != "smartrag_test" or not args.confirm_disposable:
            raise SystemExit(
                "Automatic restore requires smartrag_test and --confirm-disposable; "
                "production restore is a reviewed operator procedure"
            )
        record = json.loads(manifest.read_text())
        if record["database"] != args.database or record["sha256"] != checksum(dump):
            raise SystemExit("Backup identity/checksum mismatch")
        run([*base, "cp", str(dump), "postgres:/tmp/smartrag-restore.dump"])
        run(
            [
                *base,
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "smartrag",
                "-d",
                args.database,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--exit-on-error",
                "/tmp/smartrag-restore.dump",
            ]
        )
    print("PostgreSQL " + args.action + " completed; no dump contents were printed")


if __name__ == "__main__":
    main()
