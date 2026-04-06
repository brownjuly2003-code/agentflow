# AgentFlow: справка для аналитика

## Что это

AgentFlow — платформа данных, которая собирает события из интернет-магазина (заказы, платежи, клики, товары), обрабатывает их в реальном времени и отдаёт через API. Главные потребители API — AI-агенты (боты поддержки, аналитические ассистенты), но аналитики тоже могут использовать его напрямую.

**Зачем это нужно:** чтобы AI-агент мог ответить клиенту «ваш заказ ORD-20260404-1003 подтверждён» — ему нужны свежие данные. AgentFlow даёт эти данные с задержкой меньше 30 секунд.

## Какие данные есть

### Сущности (entities)

| Сущность | Что хранит | Ключ | Пример |
|----------|-----------|------|--------|
| **order** | Заказы: статус, сумма, пользователь | `order_id` | `ORD-20260404-1001` |
| **user** | Профиль покупателя: сколько заказов, сколько потратил | `user_id` | `USR-10001` |
| **product** | Каталог товаров: цена, наличие, остаток | `product_id` | `PROD-001` |
| **session** | Сессии на сайте: длительность, страницы, дошёл ли до покупки | `session_id` | `SES-a1b2c3` |

### Метрики (metrics)

| Метрика | Что считает | Единица |
|---------|-----------|---------|
| **revenue** | Выручка (без отменённых заказов) | USD |
| **order_count** | Количество заказов | штуки |
| **avg_order_value** | Средний чек | USD |
| **conversion_rate** | Доля сессий, дошедших до checkout | доля (0-1) |
| **active_sessions** | Активные сессии прямо сейчас | штуки |
| **error_rate** | Доля ошибочных событий в пайплайне | доля (0-1) |

Для метрик можно указать временное окно: `5m`, `15m`, `1h`, `6h`, `24h`.

## Как запустить

### Первый раз

```bash
# 1. Открой терминал в папке проекта

# 2. Установи зависимости (один раз)
make setup

# 3. Активируй виртуальное окружение
source .venv/Scripts/activate    # Windows
source .venv/bin/activate        # Mac/Linux

# 4. Запусти демо (создаст данные и поднимет API)
make demo
```

После этого:
- API работает на **http://localhost:8000**
- Документация API (Swagger): **http://localhost:8000/docs** ← открой в браузере

### В следующие разы

```bash
source .venv/Scripts/activate
make api
```

Данные сохраняются в файле `agentflow_demo.duckdb`. Если хочешь начать с чистого листа — удали этот файл и запусти `make demo` заново.

## Как запрашивать данные

Все запросы идут на `http://localhost:8000`. Можно использовать браузер, curl, Python, или Swagger UI.

### 1. Посмотреть конкретный заказ

```
GET /v1/entity/order/ORD-20260404-1001
```

Пример с curl:
```bash
curl http://localhost:8000/v1/entity/order/ORD-20260404-1001
```

Ответ:
```json
{
  "entity_type": "order",
  "entity_id": "ORD-20260404-1001",
  "data": {
    "order_id": "ORD-20260404-1001",
    "user_id": "USR-10001",
    "status": "delivered",
    "total_amount": 159.98,
    "currency": "USD"
  }
}
```

### 2. Посмотреть профиль пользователя

```
GET /v1/entity/user/USR-10001
```

Ответ покажет: сколько заказов сделал, сколько потратил, когда первый и последний заказ.

### 3. Узнать выручку за последний час

```
GET /v1/metrics/revenue?window=1h
```

Ответ:
```json
{
  "metric_name": "revenue",
  "value": 784.91,
  "unit": "USD",
  "window": "1h"
}
```

Другие окна: `?window=5m`, `?window=24h`, и т.д.

### 4. Средний чек за сегодня

```
GET /v1/metrics/avg_order_value?window=24h
```

### 5. Конверсия за последние 6 часов

```
GET /v1/metrics/conversion_rate?window=6h
```

### 6. Задать вопрос на естественном языке

```
POST /v1/query
Content-Type: application/json

{"question": "What is the average order value in the last hour?"}
```

Пример с curl:
```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me top 5 products"}'
```

Ответ содержит данные **и** SQL-запрос, который был выполнен:
```json
{
  "answer": [
    {"name": "Mechanical Keyboard", "category": "electronics", "price": 149.99, "stock_quantity": 37},
    {"name": "Running Shoes", "category": "footwear", "price": 129.99, "stock_quantity": 58}
  ],
  "sql": "SELECT name, category, price, stock_quantity FROM products_current ORDER BY price DESC LIMIT 5",
  "metadata": {
    "rows_returned": 5,
    "execution_time_ms": 2
  }
}
```

**Какие вопросы понимает система:**
- «What is the revenue today?» — выручка
- «Show me top 3 products» — топ товаров
- «What is the conversion rate in the last 24 hours?» — конверсия
- «Which products are out of stock?» — товары без остатка
- «How many active sessions right now?» — активные сессии
- Вопросы про конкретный заказ: «order ORD-20260404-1001»
- Вопросы про конкретного пользователя: «user USR-10001»

Если установлен ключ `ANTHROPIC_API_KEY`, система использует Claude для перевода любого вопроса в SQL. Без ключа работает только с шаблонами выше.

### 7. Посмотреть что вообще доступно

```
GET /v1/catalog
```

Вернёт список всех сущностей и метрик с описаниями.

### 8. Проверить здоровье системы

```
GET /v1/health
```

Ответ:
```json
{
  "status": "degraded",
  "components": [
    {"name": "kafka", "status": "unhealthy", "source": "live"},
    {"name": "flink", "status": "unhealthy", "source": "live"},
    {"name": "freshness", "status": "healthy", "source": "live"},
    {"name": "quality", "status": "healthy", "source": "live"}
  ]
}
```

- **source: "live"** — проверка реальная, данным можно доверять
- **source: "placeholder"** — проверка заглушечная, данных пока нет
- Kafka/Flink будут `unhealthy` если Docker не запущен (это нормально для локального режима без Docker)
- Freshness и quality берутся из реальных данных в DuckDB

## Как использовать из Python

```python
import httpx

API = "http://localhost:8000"

# Выручка за час
resp = httpx.get(f"{API}/v1/metrics/revenue", params={"window": "1h"})
print(resp.json()["value"])  # 784.91

# Заказ по ID
resp = httpx.get(f"{API}/v1/entity/order/ORD-20260404-1001")
order = resp.json()["data"]
print(order["status"])  # delivered

# Вопрос на естественном языке
resp = httpx.post(f"{API}/v1/query", json={
    "question": "What is the average order value today?"
})
print(resp.json()["answer"])
```

## Как использовать из Swagger UI

1. Открой **http://localhost:8000/docs** в браузере
2. Увидишь список всех эндпоинтов
3. Нажми на нужный → **Try it out** → заполни параметры → **Execute**
4. Результат появится внизу

Это самый удобный способ для первого знакомства.

## Частые вопросы

### «Получаю пустой ответ / value: 0»
Данные ещё не загружены. Запусти `make demo` — это создаст 500 тестовых событий.

### «Получаю 503 / "table not materialized"»
Таблица существует, но пуста. Запусти `make pipeline` чтобы наполнить её данными в реальном времени.

### «Получаю 404 на entity»
Либо неправильный тип сущности (доступны: order, user, product, session), либо объект с таким ID не существует.

### «Как обновить данные?»
Запусти в отдельном терминале:
```bash
make pipeline
```
Это будет генерировать и обрабатывать 10 событий в секунду. Данные появятся в API автоматически.

### «Где физически лежат данные?»
В файле `agentflow_demo.duckdb` в корне проекта. Можно открыть его напрямую через DuckDB CLI:
```bash
duckdb agentflow_demo.duckdb
```
И писать обычные SQL-запросы:
```sql
SELECT * FROM orders_v2 LIMIT 10;
SELECT COUNT(*) FROM pipeline_events;
```

### «Как подключить аутентификацию?»
Задай переменную окружения:
```bash
export AGENTFLOW_API_KEYS="sk-my-key:analyst-team"
```
После этого все запросы (кроме `/v1/health` и `/docs`) потребуют заголовок:
```bash
curl -H "X-API-Key: sk-my-key" http://localhost:8000/v1/metrics/revenue
```
