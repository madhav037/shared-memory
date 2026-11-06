# The server image, built in two parts so a deploy sends a server only what it lacks (docs/deployment.md,
# "Deploying from GitHub"):
#
# - base: what changes rarely. The system packages, the locked dependencies and the search model, over a pinned Python
#   image. Its tag is a hash of exactly what goes into it (deploy/server_base.py): everything above the release stage,
#   uv.lock, and the dependency part of pyproject.toml. While that hash holds, its layers are the ones every server
#   already has.
# - release: the server's own code on top of the base, a few megabytes. This is what a release changes.
#
# Changing anything above the release stage changes the base, and the next deploy sends it whole.

# Only pyproject.toml's dependencies reach the base, so the linters' or the tests' settings changing leaves it alone.
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS dependencies
COPY deploy/server_base.py pyproject.toml /tmp/
RUN python /tmp/server_base.py dependencies /tmp/pyproject.toml > /tmp/dependencies.toml \
    && touch -d @0 /tmp/dependencies.toml

FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.16@sha256:ae9ff79d095a61faf534a882ad6378e8159d2ce322691153d68d2afac7422840 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=dependencies /tmp/dependencies.toml ./pyproject.toml
COPY uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The search model ships in the base, so a server starts without reaching Hugging Face. The name is the server's
# (shared_memory.embeddings.MODEL, which a test holds this to); the version is fastembed's, locked in uv.lock.
ARG SEARCH_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "import sys; from fastembed import TextEmbedding; TextEmbedding(model_name=sys.argv[1], cache_dir='/opt/models')" \
    "$SEARCH_MODEL"

FROM base AS release

# The project installs editable and without compiling: compiling would rewrite every dependency's bytecode, and the
# release layer would carry all of it again.
COPY pyproject.toml LICENSE ./
COPY src ./src
RUN UV_COMPILE_BYTECODE=0 uv sync --frozen --no-dev

ENV SHARED_MEMORY_ROOT=/data/memory \
    SHARED_MEMORY_MODEL_CACHE=/opt/models
EXPOSE 8000
CMD ["shared-memory", "serve", "--host", "0.0.0.0", "--port", "8000"]
