# T18 - Chaos replay: convert Kafka timeout into replay_pending instead of 500

**Priority:** P1 - **Estimate:** 1-2ч

## Goal

Сделать path деградации при недоступном Kafka proxy предсказуемым: replay endpoint должен переводить событие в `replay_pending`, а не валиться необработанным исключением.

## Context

- TA02 audit на `a010a2d` оставил один fail в `tests/chaos/test_kafka_latency.py::test_replay_stays_pending_when_kafka_proxy_times_out`.
- Репро из теста:
  1. Поднять `docker-compose.chaos.yml`.
  2. Подменить producer через `install_deadletter_producer(...)`.
  3. Удалить toxiproxy proxy `kafka`.
  4. Вызвать `POST /v1/deadletter/{event_id}/replay`.
- Фактическое поведение:
  - producer из `tests/chaos/conftest.py:401` получает `KafkaError{code=_MSG_TIMED_OUT,...}` и бросает `RuntimeError`;
  - исключение проходит через `src/processing/outbox.py`, `src/processing/event_replayer.py` и router `deadletter`;
  - HTTP request path падает вместо возврата `{"status": "replay_pending"}`.
- Ожидаемое поведение уже зафиксировано самим тестом:
  - `replay.status_code == 200`
  - dead letter status = `("replay_pending", 1)`
  - outbox status остаётся `pending` с incremented attempt count

## Deliverables

1. Локализовать правильный слой для обработки producer timeout:
   - outbox processor,
   - event replayer,
   - либо router/service boundary.
2. Конвертировать timeout path в ожидаемое состояние `replay_pending`, не теряя signal о сбое доставки.
3. Сохранить инварианты по dead letter/outbox state, которые уже проверяет тест.
4. Получить зелёный `tests/chaos/`.

## Acceptance

- `tests/chaos/test_kafka_latency.py::test_replay_stays_pending_when_kafka_proxy_times_out` проходит.
- `tests/chaos/` зелёный целиком.
- Producer timeout не превращается в silent success: статус и retry metadata корректно отражают отложенный replay.

## Notes

- Не ослаблять test expectation как primary fix.
- Не подменять реальный timeout простой skip/xfail логикой.
