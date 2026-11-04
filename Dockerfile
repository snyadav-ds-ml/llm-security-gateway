FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install dependencies first — this layer is cached and only rebuilds
# when pyproject.toml or uv.lock changes, not on every code change.
COPY pyproject.toml uv.lock ./
# --no-install-project skips building the local src/ package (not used at runtime)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code and knowledge base
COPY phase5/ ./phase5/
COPY data/ ./data/

EXPOSE 8000
CMD [".venv/bin/uvicorn", "phase5.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
