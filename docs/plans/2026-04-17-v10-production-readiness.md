# AgentFlow — Production Readiness v10 (Phase 3)
**Date**: 2026-04-17
**Цель**: закрыть Phase 3 из BCG аудита + хвост v9
**Executor**: Codex
**Reference**: `BCG_audit.md` §8 "Phase 3", §4.2 "DevOps проблемы I1-I5"

## Откуда задачи

Phase 0 (v8) ✅, Phase 2 (v9) почти ✅. Остатки:

**Phase 3 (BCG §8):**
- I1: Terraform apply — ручной шаг, CI только `plan`
- I2: Chaos testing запускается только по расписанию, не на PR
- I3: Load testing не в PR pipeline (regression undetected до main)
- Admin dashboard (минимальный) отсутствует (§2.4 рекомендация #4)

**Хвост v9:**
- 6 оставшихся silent `except Exception:` — либо обосновать, либо закрыть

---

## Граф зависимостей

```
TASK 1  Chaos smoke в PR CI (быстрый, 5 min)            ← независим
TASK 2  Load regression gate на PR (strict threshold)   ← независим
TASK 3  Terraform apply workflow с manual approval      ← независим
TASK 4  Admin dashboard (/admin health + metrics)       ← независим
TASK 5  Закрыть хвост silent exceptions (v9 TASK 4)     ← независим
```

Все независимы. Выполнять последовательно по принципу user'а.

---

## TASK 1 — Chaos smoke в PR CI

**Сейчас:** `chaos.yml` запускается только `cron: "0 3 * * 2,4"` (2 раза в неделю) + `workflow_dispatch`. Регрессии chaos-устойчивости обнаруживаются через дни.

**Цель:** быстрый smoke chaos test на каждом PR (5 min лимит), полный run остаётся scheduled.

### Изменения

```
.github/workflows/
  chaos.yml                 # MODIFY: добавить PR trigger со smoke job
tests/chaos/
  test_chaos_smoke.py       # NEW: 2-3 самых быстрых chaos теста (< 3 min)
```

### `.github/workflows/chaos.yml`

```yaml
on:
  pull_request:
    paths:
      - 'src/**'
      - 'tests/chaos/**'
      - 'docker-compose.chaos.yml'
  schedule:
    - cron: "0 3 * * 2,4"
  workflow_dispatch:

jobs:
  chaos-smoke:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: docker compose -f docker-compose.chaos.yml up -d
      - run: pytest tests/chaos/test_chaos_smoke.py -v --timeout=120

  chaos-full:
    if: github.event_name != 'pull_request'
    # ... существующая full логика
```

### `tests/chaos/test_chaos_smoke.py`

Выбрать из существующих `tests/chaos/*.py` 2-3 наиболее быстрых теста:
- Toxiproxy latency injection → проверить что API не падает
- Random DuckDB process restart → API auto-recovers
- Redis connection drop → fallback path работает

### Verify
```bash
gh workflow run chaos.yml --ref <branch>
# Ожидаемо: PR smoke < 5 min, green
```

---

## TASK 2 — Load regression gate на PR

**Сейчас:** `load-test.yml` только на `push: [main]`. Регресс перформанса проходит в main, обнаруживается после merge.

**Цель:** strict threshold check на PR, падать если p50 вырос >20% от baseline.

### Изменения

```
.github/workflows/
  load-test.yml              # MODIFY: добавить PR trigger
scripts/
  check_performance.py       # MODIFY: поддержать --baseline flag
docs/
  benchmark-baseline.json    # EXISTS: убедиться что актуально
```

### `.github/workflows/load-test.yml`

```yaml
on:
  pull_request:
    paths: ['src/**', 'tests/load/**', 'docs/benchmark-baseline.json']
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  load-regression:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt
      - run: docker compose up -d redis
      - run: python scripts/run_benchmark.py --host http://127.0.0.1:8000 --duration 30 --users 20
      - name: Check regression
        run: python scripts/check_performance.py --baseline docs/benchmark-baseline.json --max-regress 20
```

### `scripts/check_performance.py` — добавить флаг

```python
parser.add_argument("--baseline", type=Path)
parser.add_argument("--max-regress", type=float, default=20.0,
                    help="Max p50 regression in %% from baseline before failing")

# В main():
if args.baseline:
    baseline = json.loads(args.baseline.read_text())
    for endpoint, baseline_p50 in baseline["p50_ms"].items():
        current = current_results[endpoint]["p50"]
        regress_pct = (current - baseline_p50) / baseline_p50 * 100
        if regress_pct > args.max_regress:
            print(f"REGRESSION: {endpoint} p50 {baseline_p50}→{current} (+{regress_pct:.1f}%)", file=sys.stderr)
            sys.exit(1)
```

### Обновить baseline

```bash
# Зафиксировать текущие 43ms как baseline
python scripts/run_benchmark.py
python -c "
import json
# читать docs/benchmark.md, извлечь p50/p99 per endpoint
# записать в docs/benchmark-baseline.json
"
```

### Verify
```bash
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --max-regress 20
echo "exit=$?"
# На текущей ветке — PASS. Искусственно сделать регрессию (sleep в hot path) — должно fail
```

---

## TASK 3 — Terraform apply workflow с manual approval

**Сейчас:** CI только `terraform plan`. Apply — ручной через локальный `terraform apply`. Риск drift и человеческой ошибки.

**Цель:** GH Actions workflow с environment protection (manual approval), `plan` → approval → `apply`.

### Изменения

```
.github/workflows/
  terraform-apply.yml        # NEW
infrastructure/terraform/
  environments/
    staging.tfvars.example   # NEW (BCG I5)
    prod.tfvars.example      # NEW
```

### `.github/workflows/terraform-apply.yml`

```yaml
name: Terraform Apply

on:
  workflow_dispatch:
    inputs:
      environment:
        type: choice
        options: [staging, prod]
      confirm:
        description: 'Type "APPLY" to confirm'
        required: true

permissions:
  contents: read
  id-token: write      # для OIDC auth с AWS

jobs:
  plan:
    if: inputs.confirm == 'APPLY'
    runs-on: ubuntu-latest
    outputs:
      plan-artifact: ${{ steps.plan.outputs.artifact }}
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.TF_AWS_ROLE }}
          aws-region: us-east-1
      - working-directory: infrastructure/terraform
        run: |
          terraform init
          terraform plan -var-file=environments/${{ inputs.environment }}.tfvars -out=tfplan
      - uses: actions/upload-artifact@v4
        with: { name: tfplan, path: infrastructure/terraform/tfplan }

  apply:
    needs: plan
    runs-on: ubuntu-latest
    environment:
      name: ${{ inputs.environment }}    # ← GH protection rules: required reviewer
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - uses: aws-actions/configure-aws-credentials@v4
      - uses: actions/download-artifact@v4
        with: { name: tfplan, path: infrastructure/terraform/ }
      - working-directory: infrastructure/terraform
        run: |
          terraform init
          terraform apply -auto-approve tfplan
```

### `infrastructure/terraform/environments/staging.tfvars.example`

```hcl
region              = "us-east-1"
cluster_name        = "agentflow-staging"
kafka_broker_count  = 3
flink_parallelism   = 2
# никаких реальных secrets — указать ссылку на AWS Secrets Manager ARN
# redis_auth_arn = "arn:aws:secretsmanager:..."
```

### Настройки GitHub (инструкция в README):

> Repo → Settings → Environments → Create `staging` / `prod`
> Protection rules → "Required reviewers" → добавить 1-2 человек
> Secrets → `TF_AWS_ROLE` (OIDC role ARN)

### Verify
```bash
# Локально проверить синтаксис workflow
gh workflow view terraform-apply.yml
# Локально — terraform plan на staging
cd infrastructure/terraform
terraform init
terraform plan -var-file=environments/staging.tfvars.example
```

---

## TASK 4 — Admin dashboard (минимальный)

**Сейчас:** нет UI. Operators дебажат через `curl`.

**Цель:** один HTML endpoint `/admin` с live health + топ-метрики. Без React/Next — 1 файл jinja + 1 router.

### Изменения

```
src/serving/api/routers/
  admin_ui.py                 # NEW (отдельный от admin.py который API-only)
src/serving/api/templates/
  admin.html                  # NEW (jinja)
src/serving/api/main.py       # MODIFY: register admin_ui router
tests/integration/
  test_admin_ui.py            # NEW
```

### `src/serving/api/routers/admin_ui.py`

```python
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(prefix="/admin", tags=["admin-ui"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(request: Request, _: None = Depends(require_admin_auth)):
    """Read-only admin dashboard. Polling via HTMX every 5s."""
    manager = request.app.state.auth_manager
    engine = request.app.state.query_engine

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "health": await _gather_health(request.app.state),
        "tenants": manager.list_keys_with_usage(),
        "rate_limits": manager.rate_limit_snapshot(),
        "cache_stats": await _cache_stats(request.app.state),
        "qps_1m": await _qps_last_minute(engine),
    })
```

### `src/serving/api/templates/admin.html`

Без фреймворков. Vanilla HTML + HTMX для polling.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AgentFlow Admin</title>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; background: #fafafa; color: #222; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
    .card { background: white; border: 1px solid #e5e5e5; border-radius: 8px; padding: 1.25rem; }
    .card h2 { margin: 0 0 0.75rem; font-size: 0.875rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric { font-size: 2rem; font-variant-numeric: tabular-nums; font-weight: 600; }
    .status-ok { color: #16a34a; }
    .status-warn { color: #ca8a04; }
    .status-fail { color: #dc2626; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th, td { text-align: left; padding: 0.5rem 0.25rem; border-bottom: 1px solid #f0f0f0; }
  </style>
</head>
<body>
  <h1 style="margin-bottom: 2rem;">AgentFlow Admin</h1>
  <div hx-get="/admin/partials/summary" hx-trigger="every 5s" hx-swap="innerHTML" id="dashboard">
    {% include "admin_summary.html" %}
  </div>
</body>
</html>
```

(Minimal design per user preferences: calm, clean, no overdesign. White background, subtle borders, tabular numbers for metrics.)

### Verify
```bash
make demo &
sleep 10
# Открыть в браузере http://localhost:8000/admin (с X-Admin-Key header)
# Или curl:
curl -H "X-Admin-Key: admin-secret" http://localhost:8000/admin/ | grep -c "AgentFlow Admin"
pytest tests/integration/test_admin_ui.py -v
```

### Тесты (`test_admin_ui.py`)

```python
def test_admin_requires_auth(client):
    assert client.get("/admin/").status_code == 401

def test_admin_renders_dashboard(client_with_admin):
    r = client_with_admin.get("/admin/")
    assert r.status_code == 200
    assert "<html" in r.text
    assert "AgentFlow Admin" in r.text

def test_admin_partials_update(client_with_admin):
    r = client_with_admin.get("/admin/partials/summary")
    assert r.status_code == 200
```

---

## TASK 5 — Закрыть хвост silent exceptions (v9 TASK 4 остатки)

**Оставшиеся 6 сайтов:**
- `src/processing/event_replayer.py:128`
- `src/processing/local_pipeline.py:190`
- `src/processing/outbox.py:159, 194`
- `src/quality/monitors/metrics_collector.py:220, 272` *(проверить, возможно уже исправлены)*
- `src/serving/api/analytics.py:88`

### Правило (из v9 TASK 4)

Для каждого:
1. Прочитать 20 строк контекста — понять **что может бросить** вызываемый код
2. Заменить `except Exception:` на конкретные типы ИЛИ добавить объяснительный комментарий почему catch-all оправдан (например, "rethrown by Flink pipeline")
3. Если catch-all реально оправдан (fallback path, logging only) — оставить + добавить `# nosec B110` с однострочным обоснованием, чтобы bandit не ругался

### Verify
```bash
bandit -r src/ --severity-level low 2>&1 | grep -c "B110\|B112"
# Ожидаемо: 0 или все оставшиеся явно помечены nosec с обоснованием
pytest tests/ -q --tb=line
# Ничего не сломалось
```

---

## Done When

- [ ] Chaos smoke < 5 min на каждом PR (workflow зелёный)
- [ ] Load regression workflow падает на искусственном 25% regression
- [ ] `terraform-apply.yml` существует, `workflow_dispatch` с environment protection
- [ ] `GET /admin/` рендерит HTML, защищён admin-key
- [ ] `bandit -r src/` по B110/B112 — 0 unjustified
- [ ] Full suite: 460+ passed
- [ ] BCG_audit.md — отмечены ✅ у Phase 3 чекбоксов

## Notes

- **НЕ делать** в этом раунде: Phase 1 PMF tasks (customer discovery, pricing — не-технические), SDK v2 retry/circuit-breaker (отдельный план), ClickHouse migration.
- **Admin UI:** clean, calm, white bg — без overdesign (per user preferences).
- **Terraform apply** — **не триггерить** без явной команды пользователя. Только скелет workflow, реальный apply — когда будут секреты в GH.
