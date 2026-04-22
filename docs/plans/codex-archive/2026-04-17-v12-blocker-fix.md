# AgentFlow — v11 Blocker Fix (v12)
**Date**: 2026-04-17
**Цель**: закрыть 2 реальных блокера v11, затем добить финализацию
**Executor**: Codex

## Блокеры

**B1: Performance regression** — между зелёным прогоном `.artifacts/benchmark/current.json` от 08:15:50 (entity p50 19/31/70ms) и текущим состоянием entity p50 упал до 210/300/380ms. Нужно понять: реальная регрессия в коде ИЛИ артефакт методологии (cache не прогрет, меньше users, короче run).

**B2: Terraform flink module broken** — `hashicorp/terraform:1.8` validate падает в `infrastructure/terraform/modules/flink/main.tf:61`: ресурс `aws_kinesisanalyticsv2_application` требует блок `application_code_configuration`. В текущей конфигурации его нет.

Решение: **не** принимать 08:15 артефакт как baseline. Починить оба блокера, затем вернуться к v11.

---

## Граф зависимостей

```
TASK 1  Диагностика performance regression           ← первым
TASK 2  Fix: либо code, либо benchmark methodology   ← после Task 1
TASK 3  Fix flink Terraform module                   ← независим от 1-2
TASK 4  Terraform plan smoke passes                  ← после Task 3
TASK 5  Возврат к v11 Task 1 (regen baseline)        ← после Task 2
TASK 6  v11 TASK 5 + 6 (BCG update + readiness report) ← последним
```

---

## TASK 1 — Диагностика performance regression

**Цель:** понять почему entity p50 19/31/70ms (08:15) → 210/300/380ms (сейчас). Код? Warmup? Redis down?

### Шаги

1. **Запустить старый tool-chain идентично 08:15:**
   ```bash
   docker compose up -d redis
   make api &
   sleep 15
   # ТОЧНО те же параметры что дали 08:15 результат:
   python scripts/run_benchmark.py --host http://127.0.0.1:8000 --users 50 --run-time 60s --output .tmp/bench-repro.json
   ```
   Сравнить с 08:15 артефактом:
   ```bash
   python -c "
   import json
   old = json.load(open('.artifacts/benchmark/current.json'))
   new = json.load(open('.tmp/bench-repro.json'))
   for k in new['endpoints']:
       if '/v1/entity/' not in k: continue
       o, n = old['endpoints'][k]['p50_ms'], new['endpoints'][k]['p50_ms']
       print(f'{k}: {o} -> {n} ({(n-o)/o*100:+.0f}%)')
   "
   ```

2. **Если диff > 50% — реальная регрессия.** Найти причину:
   ```bash
   # Что поменялось с 08:15?
   git log --since="2026-04-17 08:15" --oneline
   git diff HEAD src/ | head -300
   ```
   Основные подозреваемые:
   - `src/serving/api/main.py` — admin_ui router добавил middleware overhead?
   - `src/serving/api/auth/middleware.py` — правки для `/admin` bypass
   - `src/serving/api/routers/agent_query.py` — что-то тронуто?

   **Профилирование:**
   ```bash
   pip install py-spy
   make api &
   API_PID=$!
   sleep 15
   py-spy record -o .tmp/profile.svg --pid $API_PID --duration 30 --rate 100 &
   PYSPY_PID=$!
   python scripts/run_benchmark.py --host http://127.0.0.1:8000 --users 50 --run-time 30s --output /dev/null
   wait $PYSPY_PID
   # Открыть .tmp/profile.svg — найти новые широкие блоки в /v1/entity/* call path
   ```

3. **Если диф <20% — артефакт методологии.** Убедиться что baseline снимается одинаково:
   - фиксированный `users=50 run-time=60s`
   - Redis прогревается прогоном 10-20 запросов перед замером
   - `make api` поднят минимум 15s для JIT-прогрева

### Deliverable

Файл `.tmp/regression-report.md` с:
- Сравнение старого vs нового p50/p99 per endpoint
- Гипотеза причины (code / warmup / Redis)
- Если code — конкретный файл/функция из py-spy профиля
- Если methodology — какие параметры нужны для reproducible baseline

---

## TASK 2 — Fix: либо code, либо methodology

### Вариант A: реальная регрессия в коде

Наиболее вероятно — новый middleware из admin UI применяется ко всем запросам. Фикс:

```python
# src/serving/api/auth/middleware.py — bypass для /admin
# Если middleware.auth_bypass_paths уже включает /admin, то запрос /v1/entity/ не должен через него проходить.
# НО: если fastapi applied middleware ко всем запросам (включая /v1/entity), overhead мог вырасти
# Решение: проверить через middleware timing (X-Auth-Middleware-Duration-Ms header)
```

Инструменировать middleware:
```python
import time
start = time.perf_counter()
response = await call_next(request)
response.headers["X-Auth-Middleware-Duration-Ms"] = f"{(time.perf_counter()-start)*1000:.1f}"
return response
```

Прогнать бенчмарк — если header показывает 100ms+ — узкое место найдено.

Возможные фиксы:
- Cache auth result в request scope
- Убрать дорогие ops (list_keys_with_usage) из hot path
- Если bcrypt verify в hot path — кешировать (plaintext_hash → tenant_key) на 60s

### Вариант B: methodology

Если регрессия — артефакт:
1. Добавить warmup step в `scripts/run_benchmark.py`:
   ```python
   def warmup(host, duration=10):
       """Pre-warm the API: cache + JIT."""
       import requests
       deadline = time.time() + duration
       while time.time() < deadline:
           for endpoint in ["/v1/health", "/v1/entity/order/ORD-20260401-0001"]:
               try: requests.get(f"{host}{endpoint}", timeout=1)
               except: pass
   ```
   Вызывать перед main loop.

2. Зафиксировать "canonical" benchmark params в `scripts/run_benchmark.py`:
   ```python
   CANONICAL_PARAMS = {"users": 50, "spawn_rate": 10, "run_time": "60s", "warmup_seconds": 10}
   ```
   Если пользователь передал меньшие числа — предупреждение "below canonical baseline, results not comparable".

### Verify
```bash
# Повторный прогон с фиксом
python scripts/run_benchmark.py --host http://127.0.0.1:8000 --users 50 --run-time 60s --output .tmp/bench-post-fix.json
python -c "
import json
r = json.load(open('.tmp/bench-post-fix.json'))
for k, d in r['endpoints'].items():
    if '/v1/entity/' in k:
        assert d['p50_ms'] < 100, f'STILL REGRESSED: {k} p50={d[\"p50_ms\"]}'
print('entity p50 all < 100ms — regression fixed')
"
```

---

## TASK 3 — Fix flink Terraform module

**Проблема:** `infrastructure/terraform/modules/flink/main.tf:61` — `aws_kinesisanalyticsv2_application` без required block `application_code_configuration`.

### Минимальный валидный блок

Согласно [AWS provider docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kinesisanalyticsv2_application), `application_code_configuration` требует как минимум `code_content_type` и один из `code_content` / `s3_content_location`.

```hcl
resource "aws_kinesisanalyticsv2_application" "this" {
  name                   = var.application_name
  runtime_environment    = "FLINK-1_19"
  service_execution_role = aws_iam_role.flink.arn

  application_configuration {
    application_code_configuration {
      code_content_type = "ZIPFILE"
      code_content {
        s3_content_location {
          bucket_arn = var.jar_s3_bucket_arn
          file_key   = var.jar_s3_key
        }
      }
    }

    flink_application_configuration {
      checkpoint_configuration {
        configuration_type = "DEFAULT"
      }
      monitoring_configuration {
        configuration_type = "DEFAULT"
      }
      parallelism_configuration {
        configuration_type = "CUSTOM"
        parallelism        = var.parallelism
        auto_scaling_enabled = true
      }
    }
  }
}
```

Также добавить переменные в `modules/flink/variables.tf`:
```hcl
variable "jar_s3_bucket_arn" {
  type        = string
  description = "S3 bucket ARN где лежит Flink JAR"
}
variable "jar_s3_key" {
  type        = string
  description = "S3 key для Flink application JAR"
  default     = "flink/agentflow-app.jar"
}
```

И пробросить в `staging.tfvars.example` / `prod.tfvars.example`:
```hcl
jar_s3_bucket_arn = "arn:aws:s3:::<REPLACE-ME-bucket>"
jar_s3_key        = "flink/agentflow-app.jar"
```

### Verify
```bash
cd infrastructure/terraform
docker run --rm -v "$PWD:/w" -w /w hashicorp/terraform:1.8 init -backend=false
docker run --rm -v "$PWD:/w" -w /w hashicorp/terraform:1.8 validate
# Ожидаемо: Success! The configuration is valid.
docker run --rm -v "$PWD:/w" -w /w hashicorp/terraform:1.8 plan -var-file=environments/staging.tfvars.example -input=false -lock=false
# Ожидаемо: plan succeeds (может ругаться на AWS credentials — это нормально; grep "Missing required argument" — не должно быть)
```

---

## TASK 4 — Terraform plan smoke passes (v11 Task 3 закрыть)

**После Task 3** — прогнать plan для обоих environments:

```bash
cd infrastructure/terraform
for env in staging prod; do
  docker run --rm -v "$PWD:/w" -w /w hashicorp/terraform:1.8 plan \
    -var-file=environments/${env}.tfvars.example -input=false -lock=false 2>&1 | tail -20
  echo "${env}: validate complete"
done
```

### Verify
- Оба environments: plan без ошибок "Missing required argument"
- AWS credentials errors — OK (не реальный apply)

---

## TASK 5 — Regen benchmark baseline (v11 Task 1)

**После Task 2** — когда реально p50 < 100ms стабильно воспроизводится:

```bash
docker compose up -d redis
make api &
sleep 15
python scripts/run_benchmark.py --host http://127.0.0.1:8000 --users 50 --run-time 60s --output docs/benchmark-baseline.json
kill %1
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current docs/benchmark-baseline.json --max-regress 20
echo "exit=$?"  # 0
```

---

## TASK 6 — BCG audit + release readiness (v11 Task 5-6)

Выполнить v11 TASK 5 и TASK 6 как описано в `docs/plans/2026-04-17-v11-finalization.md`. Отметки ✅ в `BCG_audit.md` проставляются только для **реально подтверждённых** пунктов (после Task 1-5).

---

## Финальный отчёт

```
## v12 Blocker Fix — результат

### TASK 1: Regression diagnostic
- Cause: <code / methodology / other>
- Evidence: <py-spy profile / benchmark diff / commit range>
- File of blame (если code): <path:line>

### TASK 2: Fix applied
- Approach: <A: code fix / B: methodology>
- Entity p50 после фикса: <order/product/user = X/Y/Z ms>

### TASK 3-4: Terraform
- Module fix: <commit hash / path>
- validate: <OK>
- plan staging: <OK / failed с причиной>
- plan prod: <OK / failed с причиной>

### TASK 5-6: v11 closure
- benchmark-baseline.json regen: <timestamp, entity p50 values>
- BCG_audit.md: <N items marked ✅>
- docs/release-readiness.md: <created Y/N>

### Full suite
pytest tests/unit tests/integration --tb=line -q
Результат: <N passed, M failed>

### Open items
<Конкретно что не удалось и почему>
```

## Notes

- **TASK 1 — диагностика, не прыгать сразу к Вариант A или Б.** Сначала replicate, измерить, потом фиксить.
- **НЕ подгонять baseline** под медленный результат "чтобы пройти". Причина регрессии должна быть найдена и зафиксирована.
- **Terraform apply реально НЕ запускать** — только validate + plan в docker. Никаких `apply`.
