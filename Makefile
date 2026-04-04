.PHONY: up down produce api test quality lint format build deploy-dev wait-healthy clean

# ── Local Development ─────────────────────────────────────────────

up:
	docker compose up -d
	@echo "Starting services... Use 'make wait-healthy' to wait for readiness."

down:
	docker compose down -v

wait-healthy:
	@echo "Waiting for Kafka..."
	@timeout 60 bash -c 'until docker compose exec kafka kafka-broker-api-versions --bootstrap-server localhost:9092 > /dev/null 2>&1; do sleep 2; done'
	@echo "Waiting for Flink JobManager..."
	@timeout 60 bash -c 'until curl -sf http://localhost:8081/overview > /dev/null 2>&1; do sleep 2; done'
	@echo "Waiting for MinIO..."
	@timeout 30 bash -c 'until curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; do sleep 2; done'
	@echo "All services ready."

produce:
	python -m src.ingestion.producers.event_producer

api:
	uvicorn src.serving.api.main:app --host 0.0.0.0 --port 8000 --reload

# ── Testing ───────────────────────────────────────────────────────

test:
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/unit/ -v --tb=short

test-integration:
	pytest tests/integration/ -v --tb=short -m integration

quality:
	python -m src.quality.monitors.freshness_monitor
	python -m src.quality.validators.semantic_validator --check-all

# ── Code Quality ──────────────────────────────────────────────────

lint:
	ruff check src/ tests/
	mypy src/ --ignore-missing-imports

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
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ dist/ build/ *.egg-info
