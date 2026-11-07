"""Restore drill restricted to the disposable test Compose project/database."""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def sql(statement: str) -> str:
    process = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "smartrag-test",
            "-f",
            "docker-compose.test.yml",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "smartrag",
            "-d",
            "smartrag_test",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atc",
            statement,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise SystemExit("Disposable restore drill failed; private subprocess output suppressed")
    return process.stdout.strip()


def main() -> None:
    directory = Path(".backups") / ("drill-" + uuid4().hex)
    sql(
        "CREATE TABLE smartrag_restore_probe(value integer); "
        "INSERT INTO smartrag_restore_probe VALUES (42)"
    )
    started = time.perf_counter()
    common = [
        "--project",
        "smartrag-test",
        "--compose",
        "docker-compose.test.yml",
        "--database",
        "smartrag_test",
        "--directory",
        str(directory),
    ]
    for action in ["backup", "restore"]:
        if action == "restore":
            sql("DELETE FROM smartrag_restore_probe")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.database_backup",
                action,
                *common,
                *(["--confirm-disposable"] if action == "restore" else []),
            ],
            check=False,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    passed = sql("SELECT value FROM smartrag_restore_probe") == "42"
    sql("DROP TABLE smartrag_restore_probe")
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "database": "smartrag_test",
        "backup_checksum_verified": True,
        "restored_canary": passed,
        "seconds": time.perf_counter() - started,
        "scope": "local PostgreSQL schema/data only; not S3/Qdrant or hosted disaster recovery",
    }
    Path("evaluation/release/restore.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
