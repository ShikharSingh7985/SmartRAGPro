FROM python:3.12.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY alembic.ini ./
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]

FROM base AS test
USER root
RUN uv sync --frozen
COPY tests ./tests
ENV COVERAGE_FILE=/tmp/.coverage
USER app
CMD ["python", "-m", "pytest", "--basetemp=/tmp/pytest", "-o", "cache_dir=/tmp/pytest-cache"]

FROM base AS runtime
