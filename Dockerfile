FROM python:3.12.12-slim AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken
RUN .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" && chmod -R a+rX /opt/tiktoken
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

FROM dependencies AS base
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY alembic.ini ./
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]

FROM base AS test
USER root
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
COPY tests ./tests
COPY evaluation ./evaluation
ENV COVERAGE_FILE=/tmp/.coverage
USER app
CMD ["python", "-m", "pytest", "--basetemp=/tmp/pytest", "-o", "cache_dir=/tmp/pytest-cache"]

FROM dependencies AS worker
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra parsing --no-dev --no-install-project
RUN mkdir -p /tmp/model-cache && chown 10001:10001 /tmp/model-cache
ENV HF_HOME=/tmp/model-cache OMP_NUM_THREADS=2
COPY backend ./backend
COPY scripts ./scripts
COPY alembic.ini ./
USER app

FROM base AS frontend
EXPOSE 8501
CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]

FROM base AS runtime
