FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.16 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    SHARED_MEMORY_ROOT=/data/memory \
    SHARED_MEMORY_MODEL_CACHE=/data/models
EXPOSE 8000
CMD ["shared-memory", "serve", "--host", "0.0.0.0", "--port", "8000"]
