# AgentFlow — public read-only demo for Hugging Face Docker Spaces.
#
# Builds the serving API from the public GitHub repo and runs it in demo mode
# (seeded DuckDB, admin routes 404, mutating routes blocked except /v1/query).
# Mirrors Dockerfile.api / deploy/fly — the same single-container demo, repointed
# at Spaces' port + writable-home conventions.
#
# Local / Mac verify (context is this directory; the repo is cloned at build time):
#   docker build -t agentflow-hf deploy/hf-space
#   docker run --rm -p 8000:8000 agentflow-hf
#   curl -fsS http://localhost:8000/v1/health
#   curl -fsS -H "X-API-Key: demo-key" http://localhost:8000/v1/entity/order/ORD-20260404-1001

FROM python:3.11-slim@sha256:ae52c5bef62a6bdd42cd1e8dffef86b9cd284bde9427da79839de7a4b983e7ca AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Track main by default; pin to a tag/sha with --build-arg AGENTFLOW_REF=v1.5.0
ARG AGENTFLOW_REF=main
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${AGENTFLOW_REF}" \
        https://github.com/brownjuly2003-code/agentflow.git /src
WORKDIR /src
RUN pip install --no-cache-dir --upgrade pip build hatchling \
    && python -m build --wheel --outdir /tmp/dist

FROM python:3.11-slim@sha256:ae52c5bef62a6bdd42cd1e8dffef86b9cd284bde9427da79839de7a4b983e7ca

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV AGENTFLOW_ENTITY_CONTRACTS_DIR=/app/contracts/entities

# Demo mode (mirrors deploy/fly/README.md): injected public key, admin routes
# return 404, mutating routes blocked except POST /v1/query[/explain], DuckDB
# seeded on first boot. Data lives under the demo user's writable home.
# config/serving.yaml defaults to ClickHouse (ADR 0006 Phase 1); the
# single-container demo runs none, so pin the embedded DuckDB backend.
ENV SERVING_BACKEND=duckdb
ENV AGENTFLOW_DEMO_MODE=true
ENV AGENTFLOW_SEED_ON_BOOT=true
ENV DEMO_API_KEY=demo-key
ENV DUCKDB_PATH=/home/user/data/agentflow-demo.duckdb
ENV AGENTFLOW_USAGE_DB_PATH=/home/user/data/agentflow-demo-api.duckdb

COPY --from=builder /src/requirements.txt /app/requirements.txt
COPY --from=builder /src/config /app/config
COPY --from=builder /src/contracts /app/contracts
COPY --from=builder /tmp/dist /tmp/dist

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --upgrade setuptools==82.0.1 wheel==0.47.0 \
    && pip install --no-cache-dir -r requirements.txt \
    && wheel="$(find /tmp/dist -name '*.whl' -print -quit)" \
    && pip install --no-cache-dir "${wheel}[cloud]" \
    && pip install --no-cache-dir bcrypt PyYAML sqlglot \
    && rm -rf /tmp/dist

# Hugging Face Spaces runs the container as UID 1000 with $HOME=/home/user.
RUN useradd -m -u 1000 user \
    && mkdir -p /home/user/data \
    && chown -R user:user /home/user/data
USER user
ENV HOME=/home/user

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "src.serving.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
