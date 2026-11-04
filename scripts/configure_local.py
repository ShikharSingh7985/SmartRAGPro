"""Create private local credentials without printing them or replacing an existing .env."""

import secrets
from pathlib import Path


def main() -> None:
    template = Path(".env.example").read_text(encoding="utf-8")
    database_password = secrets.token_urlsafe(36)
    configured = (
        template.replace("CHANGE_ME_DB_PASSWORD", database_password)
        .replace("CHANGE_ME_GENERATE_AT_LEAST_32_RANDOM_CHARACTERS", secrets.token_urlsafe(48))
        .replace("CHANGE_ME_STORAGE_PASSWORD", secrets.token_urlsafe(36))
    )
    try:
        with Path(".env").open("x", encoding="utf-8") as target:
            target.write(configured)
    except FileExistsError:
        raise SystemExit("Existing .env preserved. Configure it locally.") from None
    print("Created ignored .env with random local credentials. Set GEMINI_API_KEY locally.")


if __name__ == "__main__":
    main()
