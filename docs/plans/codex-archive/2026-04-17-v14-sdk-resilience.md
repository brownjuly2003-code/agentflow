# AgentFlow — SDK Resilience v14 (post-release Phase 4)
**Date**: 2026-04-17
**Цель**: закрыть BCG §3.4 rec #9 — SDK без retry/backoff/circuit-breaker + p99 entity followup
**Executor**: Codex
**Reference**: `BCG_audit.md` §3.2 "Dual SDK" недостатки, §3.4 rec #9

## Контекст

v1.0.0 релиз технически готов. Из BCG §3.2 осталось:
- Python SDK и TS SDK **не имеют retry/backoff** на transient failures (429, 503, network errors)
- **Нет circuit breaker** — каскадные сбои при недоступности backend
- **p99 entity 290-320ms** — хуже чем до v12 регрессии (170ms), внутри gate, но кандидат на оптимизацию

Эти пункты — реальная ценность для пользователей SDK, не блокер.

---

## Граф зависимостей

```
TASK 1  Python SDK: retry + exponential backoff с jitter    ← независим
TASK 2  Python SDK: circuit breaker                         ← после Task 1
TASK 3  TypeScript SDK: parity Task 1+2                     ← после Task 1+2
TASK 4  p99 entity followup (170→290ms)                     ← независим
```

---

## TASK 1 — Python SDK retry/backoff

### Что построить

```
sdk/agentflow/
  retry.py                  # NEW: RetryPolicy, compute_backoff
  client.py                 # MODIFY: обернуть _request в retry
  async_client.py           # MODIFY: аналогично
tests/
  sdk/test_retry.py         # NEW
```

### `sdk/agentflow/retry.py`

```python
"""Retry policy with exponential backoff + jitter.

Retries on: 429 (Retry-After respected), 502, 503, 504, network errors.
Does NOT retry on: 4xx (except 429), 5xx where idempotency unsafe (POST with side-effects).
"""
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")

RETRYABLE_STATUS = {429, 502, 503, 504}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_INITIAL_DELAY_S = 0.25
DEFAULT_MAX_DELAY_S = 30.0
DEFAULT_JITTER_FACTOR = 0.3


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    initial_delay_s: float = DEFAULT_INITIAL_DELAY_S
    max_delay_s: float = DEFAULT_MAX_DELAY_S
    jitter_factor: float = DEFAULT_JITTER_FACTOR

    def compute_delay(self, attempt: int, retry_after_s: float | None = None) -> float:
        """attempt is 0-indexed; attempt=0 means before first retry."""
        if retry_after_s is not None:
            return min(retry_after_s, self.max_delay_s)
        base = min(self.initial_delay_s * (2 ** attempt), self.max_delay_s)
        jitter = random.uniform(-base * self.jitter_factor, base * self.jitter_factor)
        return max(0.0, base + jitter)


def is_retryable_method(method: str) -> bool:
    """Idempotent methods + POST with explicit idempotency-key header (handled by caller)."""
    return method.upper() in {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}
```

### Интеграция в `sdk/agentflow/client.py`

```python
from .retry import RetryPolicy, RETRYABLE_STATUS, is_retryable_method

class Client:
    def __init__(self, ..., retry_policy: RetryPolicy | None = None):
        self._retry = retry_policy or RetryPolicy()

    def _request(self, method, url, **kwargs):
        attempt = 0
        while True:
            try:
                response = self._session.request(method, url, **kwargs)
            except (ConnectionError, TimeoutError) as exc:
                if attempt >= self._retry.max_attempts - 1 or not is_retryable_method(method):
                    raise
                delay = self._retry.compute_delay(attempt)
                logger.info("sdk_retry_network", attempt=attempt, delay_s=delay, exc=str(exc))
                time.sleep(delay)
                attempt += 1
                continue

            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= self._retry.max_attempts - 1 or not is_retryable_method(method):
                return response

            retry_after = response.headers.get("Retry-After")
            delay = self._retry.compute_delay(
                attempt,
                retry_after_s=float(retry_after) if retry_after else None,
            )
            logger.info("sdk_retry_status", attempt=attempt, status=response.status_code, delay_s=delay)
            time.sleep(delay)
            attempt += 1
```

**Аналогично в `async_client.py`** — через `asyncio.sleep`.

### Тесты (`tests/sdk/test_retry.py`)

```python
def test_retry_policy_exponential_backoff():
    p = RetryPolicy(max_attempts=5, initial_delay_s=0.1, jitter_factor=0)
    assert p.compute_delay(0) == 0.1
    assert p.compute_delay(1) == 0.2
    assert p.compute_delay(2) == 0.4

def test_retry_policy_respects_retry_after():
    p = RetryPolicy()
    assert p.compute_delay(0, retry_after_s=3.0) == 3.0

def test_retry_policy_caps_at_max_delay():
    p = RetryPolicy(max_delay_s=1.0, jitter_factor=0)
    assert p.compute_delay(10) == 1.0

def test_client_retries_on_503(mock_http):
    mock_http.get("/v1/entity/order/X", [
        {"status": 503},
        {"status": 503},
        {"status": 200, "body": {"ok": True}},
    ])
    client = Client(base_url="...", retry_policy=RetryPolicy(initial_delay_s=0.01))
    result = client.get_entity("order", "X")
    assert mock_http.call_count == 3

def test_client_does_not_retry_post_by_default(mock_http):
    mock_http.post("/v1/batch", [{"status": 503}])
    with pytest.raises(HTTPError):
        client.batch([{...}])
    assert mock_http.call_count == 1

def test_client_respects_retry_after_header(mock_http, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    mock_http.get("/v1/entity/X", [
        {"status": 429, "headers": {"Retry-After": "2"}},
        {"status": 200, "body": {"ok": True}},
    ])
    client.get_entity("order", "X")
    assert sleep_calls == [2.0]
```

### Verify
```bash
pytest tests/sdk/test_retry.py -v
# 5+ tests passed
```

---

## TASK 2 — Python SDK circuit breaker

### Что построить

```
sdk/agentflow/
  circuit_breaker.py        # NEW
  client.py                 # MODIFY: integrate breaker
tests/sdk/
  test_circuit_breaker.py   # NEW
```

### `sdk/agentflow/circuit_breaker.py`

Simplified 3-state breaker: closed → open → half-open.

```python
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    reset_timeout_s: float = 30.0
    half_open_max_calls: int = 1

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def before_call(self) -> None:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self.reset_timeout_s:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                else:
                    raise CircuitOpenError("circuit is open")
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitOpenError("circuit is half-open, probe in flight")
                self._half_open_calls += 1

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    @property
    def state(self) -> CircuitState:
        return self._state
```

### Интеграция

```python
class Client:
    def __init__(self, ..., circuit_breaker: CircuitBreaker | None = None):
        self._breaker = circuit_breaker or CircuitBreaker()

    def _request(self, method, url, **kwargs):
        self._breaker.before_call()
        try:
            response = ...  # existing retry logic from Task 1
            if response.status_code < 500:
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
            return response
        except (ConnectionError, TimeoutError):
            self._breaker.record_failure()
            raise
```

### Тесты

```python
def test_breaker_opens_after_threshold():
    b = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        b.record_failure()
    assert b.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        b.before_call()

def test_breaker_resets_after_timeout():
    b = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)
    b.record_failure()
    time.sleep(0.15)
    b.before_call()  # transitions to half-open
    assert b.state == CircuitState.HALF_OPEN

def test_breaker_half_open_success_closes():
    b = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)
    b.record_failure()
    time.sleep(0.15)
    b.before_call()
    b.record_success()
    assert b.state == CircuitState.CLOSED

def test_breaker_half_open_failure_reopens():
    b = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)
    b.record_failure()
    time.sleep(0.15)
    b.before_call()
    b.record_failure()
    assert b.state == CircuitState.OPEN

def test_breaker_allows_one_probe_in_half_open():
    b = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1, half_open_max_calls=1)
    b.record_failure()
    time.sleep(0.15)
    b.before_call()
    with pytest.raises(CircuitOpenError):
        b.before_call()  # second probe blocked
```

### Verify
```bash
pytest tests/sdk/test_circuit_breaker.py -v
# 5+ tests passed
```

---

## TASK 3 — TypeScript SDK parity

**Цель:** идентичный API для retry + circuit breaker в TS SDK (BCG §3.2 принцип паритета).

```
sdk-ts/src/
  retry.ts                  # NEW
  circuitBreaker.ts         # NEW
  client.ts                 # MODIFY
tests/
  retry.test.ts             # NEW (или в sdk-ts/tests/)
  circuitBreaker.test.ts    # NEW
```

### Ключевые моменты

- Interfaces 1-в-1 с Python: `RetryPolicy { maxAttempts, initialDelayMs, maxDelayMs, jitterFactor }`, `CircuitBreaker { failureThreshold, resetTimeoutMs, halfOpenMaxCalls }`
- Async retry через `await new Promise(r => setTimeout(r, delay))`
- Tests: Jest/Vitest (что используется в проекте)

### Verify
```bash
cd sdk-ts
npm test
# retry.test.ts + circuitBreaker.test.ts green
```

---

## TASK 4 — p99 entity followup (170→290ms)

**Цель:** вернуть p99 entity к pre-regression уровню (~170ms) или объяснить почему 290ms — новый normal.

### Диагностика

```bash
docker compose up -d redis
make api &
sleep 20
# py-spy на 60s под нагрузкой
py-spy record -o .tmp/p99-profile.svg --pid $(pgrep -f "uvicorn.*main") --duration 60 --rate 100 &
python scripts/run_benchmark.py --host http://127.0.0.1:8000 --users 50 --run-time 60s --output .tmp/p99.json
wait
```

Открыть `.tmp/p99-profile.svg`, найти самый широкий tail-блок (что делает SDK/API на 1-2% самых медленных запросах).

### Типичные подозреваемые p99 tail

1. **bcrypt verify** — 15-50ms на первый запрос API-key. Cache `(plaintext_hash → tenant_key)` с TTL 60s.
2. **DuckDB query планирование** — для redkih запросов DuckDB планирует с нуля. Prepared statements + cache plans.
3. **GC pause** — Python GC на больших objects. `gc.freeze()` при старте API.
4. **Cold Redis connection** — первый запрос к Redis создаёт коннект. Pre-warm pool.
5. **Middleware stack** — 6 слоёв — какая-то из них случайно делает sync I/O.

### Фикс (выбрать 1-2 наиболее weighty из профиля)

Наиболее вероятно — **bcrypt в hot path**. Фикс:

```python
# src/serving/api/auth/manager.py — add bcrypt verification cache
from functools import lru_cache
from cachetools import TTLCache

class AuthManager:
    def __init__(self, ...):
        self._verify_cache = TTLCache(maxsize=1024, ttl=60)

    def _verify_cached(self, api_key: str, key_hash: str) -> bool:
        cache_key = (api_key, key_hash)
        if cache_key in self._verify_cache:
            return self._verify_cache[cache_key]
        result = verify_api_key(api_key, key_hash)
        self._verify_cache[cache_key] = result
        return result
```

Использовать `_verify_cached` вместо `verify_api_key` в `authenticate`.

**Security note:** cache key содержит plaintext — OK поскольку in-process memory, но **не логировать** и **не persistить** cache. TTL 60s ограничивает blast radius если memory leak.

### Verify

```bash
python scripts/run_benchmark.py --users 50 --run-time 60s --output .tmp/bench-p99fix.json
python -c "
import json
b = json.load(open('.tmp/bench-p99fix.json'))
for k, d in b['endpoints'].items():
    if '/v1/entity/' in k:
        p99 = d['p99_ms']
        print(f'{k}: p99={p99}ms', 'FIXED' if p99 < 200 else 'STILL HIGH')
"
# Target: все entity p99 < 200ms
# Если < 200ms — обновить docs/benchmark-baseline.json
# Если >= 200ms — зафиксировать в regression-report.md что это предел без более глубокой оптимизации
```

---

## Done When

- [ ] Python SDK: retry + circuit breaker, 10+ новых тестов
- [ ] TypeScript SDK: retry + circuit breaker, parity с Python
- [ ] p99 entity: либо <200ms, либо задокументировано объяснение почему 290ms — ок
- [ ] CHANGELOG обновлён (sdk/CHANGELOG.md + sdk-ts/CHANGELOG.md)
- [ ] BCG_audit.md §3.2 обновлён: "Нет retry/backoff" → ✅, "Нет circuit breaker" → ✅
- [ ] Полный прогон: 520+ passed (было 508), 0 failed

## Notes

- **Task 1 → Task 2 → Task 3 (parity)** — последовательно.
- **Task 4 независим** — можно начать параллельно если Codex захочет, но помни правило пользователя про sequential.
- **Не добавлять** в этом раунде: streaming SDK, SSE auto-reconnect (это v2 фичи).
- **Не менять публичный API SDK** — только добавить новые опциональные параметры с defaults.
