# One image, four services.
#
# The simulator, both MCP servers, and the backend share this image and differ only
# by their command. That is a deliberate trade: four near-identical Dockerfiles would
# each rebuild the same dependency layer, and the extras that differ between them are
# a few megabytes of pure Python. One image means one layer cache, one build, and one
# place where the Python version is pinned.
#
# The frontend has its own Dockerfile — it shares nothing with these.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is here for the healthchecks in docker-compose.yml, which need something
# inside the container that can make an HTTP request.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# --- dependency layer -------------------------------------------------------
# Only the files that determine the dependency set are copied first, so editing
# source code does not invalidate the (slow) install layer.
COPY pyproject.toml README.md LICENSE ./
COPY rag/__init__.py rag/__init__.py
COPY connectors/alarm_api/__init__.py connectors/alarm_api/__init__.py
COPY packages/schemas/copilot_schemas/__init__.py packages/schemas/copilot_schemas/__init__.py
COPY apps/backend/copilot_backend/__init__.py apps/backend/copilot_backend/__init__.py
COPY services/alarm-simulator/alarm_simulator/__init__.py services/alarm-simulator/alarm_simulator/__init__.py
COPY mcp-servers/alarm-management/alarm_mcp/__init__.py mcp-servers/alarm-management/alarm_mcp/__init__.py
COPY mcp-servers/github-issues/github_mcp/__init__.py mcp-servers/github-issues/github_mcp/__init__.py

RUN pip install --no-cache-dir ".[simulator,mcp,backend,rag]"

# --- source layer -----------------------------------------------------------
COPY rag ./rag
COPY connectors ./connectors
COPY packages ./packages
COPY apps/backend ./apps/backend
COPY services ./services
COPY mcp-servers ./mcp-servers
COPY scripts ./scripts

# Reinstall so the wheel contains the real source, not just the __init__ stubs.
RUN pip install --no-cache-dir --no-deps .

# Runs unprivileged. /data holds the SQLite file and the Chroma index, both of which
# are created at runtime, so the directory must be writable by this user.
RUN useradd --create-home --uid 10001 copilot \
 && mkdir -p /data \
 && chown -R copilot:copilot /data /app
USER copilot

# Overridden per service in docker-compose.yml.
CMD ["uvicorn", "copilot_backend.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
