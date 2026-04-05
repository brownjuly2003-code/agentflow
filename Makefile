.PHONY: up down produce api test quality lint format build deploy-dev wait-healthy clean setup demo pipeline load-test

# ── Setup ─────────────────────────────────────────────────────────

setup:
	python -m venv .venv
	.venv/Scripts/pip install -e ".[dev]" 2>/dev/null || .venv/bin/pip install -e ".[dev]"
	@echo "Setup complete. Activate with: source .venv/Scripts/activate (Windows) or source .venv/bin/activate (Unix)"

# ── Local Development ─────────────────────────────────────────────

up:
	docker compose up -d
	@echo "Starting services... Use 'make wait-healthy' to wait for readiness."

down:
	docker compose down -v

wait-healthy:
	@echo "Waiting for services..."
	python -c "import time, urllib.request; [time.sleep(2) for _ in range(30) if not (lambda: (urllib.request.urlopen('http://localhost:8081/overview'), True)[-1])()]" 2>/dev/null || echo "Flink not ready yet"
	@echo "Check service health at: http://localhost:8081 (Flink), http://localhost:9001 (MinIO)"

produce:
	python -m src.ingestion.producers.event_producer

api:
	DUCKDB_PATH=agentflow_demo.duckdb uvicorn src.serving.api.main:app --host 0.0.0.0 --port 8000 --reload

# ── End-to-End Demo (no Docker needed) ───────────────────────────

demo:
	@echo "=== AgentFlow Demo ==="
	@echo "Step 1: Seeding 500 events through the full pipeline..."
	python -m src.processing.local_pipeline --burst 500
	@echo ""
	@echo "Step 2: Starting API server (Ctrl+C to stop)..."
	@echo "  Open http://localhost:8000/docs"
	@echo "  Try:  curl http://localhost:8000/v1/metrics/revenue?window=24h"
	@echo "  Try:  curl http://localhost:8000/v1/entity/user/USR-10001"
	@echo "  Try:  curl http://localhost:8000/v1/health"
	DUCKDB_PATH=agentflow_demo.duckdb uvicorn src.serving.api.main:app --host 0.0.0.0 --port 8000

pipeline:
	python -m src.processing.local_pipeline --eps 10

# ── Testing ───────────────────────────────────────────────────────

test:
	pytest tests/ -v --tb=short --ignore=tests/load

test-unit:
	pytest tests/unit/ -v --tb=short

test-integration:
	pytest tests/integration/ -v --tb=short -m integration

quality:
	python -m src.quality.validators.semantic_validator --check-all

# ── Load Testing ──────────────────────────────────────────────────

load-test:
	@echo "Starting load test (50 users, 60s). API must be running on :8000"
	locust -f tests/load/locustfile.py --host http://localhost:8000 --headless -u 50 -r 10 --run-time 60s

# ── Code Quality ──────────────────────────────────────────────────

lint:
	ruff check src/ tests/
	mypy src/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# ── Build & Deploy ────────────────────────────────────────────────

build:
	docker compose build

deploy-dev:
	cd infrastructure/terraform && terraform init && terraform plan -var-file=dev.tfvars

deploy-prod:
	cd infrastructure/terraform && terraform init && terraform plan -var-file=prod.tfvars
	@echo "Review the plan above. Run 'terraform apply' manually to proceed."

# ── Cleanup ───────────────────────────────────────────────────────

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]" 2>/dev/null || true
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]" 2>/dev/null || true
	python -c "import shutil; [shutil.rmtree(p, True) for p in ['.coverage', 'htmlcov', 'dist', 'build']]" 2>/dev/null || true
	python -c "import pathlib; [p.unlink() for p in pathlib.Path('.').glob('*.duckdb*')]" 2>/dev/null || true
