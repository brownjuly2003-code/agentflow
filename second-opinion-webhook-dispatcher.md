# Second Opinion Prompt: Webhook Dispatcher Strict Mypy Slice

Claude CLI timed out while requesting this focused review on 2026-05-31.
Do not start the risky `src.serving.api.webhook_dispatcher` strict-mypy slice
until a second opinion answers this prompt or the operator explicitly overrides
the second-opinion requirement.

```text
You are giving a focused second opinion for a risky typing-only slice in a
Python/FastAPI repo.

Goal: promote `src.serving.api.webhook_dispatcher` to a mypy override with
`disallow_untyped_defs = true`, preserving runtime behavior. No refactor, no
auth/hash-format changes, no DB schema changes.

Current facts:
- Project mypy has `disallow_untyped_defs = false`, `check_untyped_defs = true`,
  `warn_return_any = true`; strict slices only set `disallow_untyped_defs = true`
  per module.
- Remaining untyped public AST count for this file is 1, but mypy strict will
  also require private method/function annotations.
- Relevant current signatures in `src/serving/api/webhook_dispatcher.py`:
  - `def get_webhook_config_path(app) -> Path:` uses
    `getattr(app.state, "webhook_config_path", None)`.
  - `def get_delivery_logs(conn: duckdb.DuckDBPyConnection, webhook_id: str) -> list[dict]:`
    returns DuckDB rows as dicts.
  - `class WebhookDispatcher:`
    - `def __init__(self, app, poll_interval_seconds: float = 2.0) -> None:`
      stores `self.app = app`.
    - `async def deliver(self, webhook: WebhookRegistration, event: dict) -> dict:`
      posts signed webhook body and returns delivery metadata.
    - `def _fetch_pipeline_events(self, tenant: str | None = None) -> list[dict]:`
      reads DuckDB rows as dicts.
  - Helpers:
    - `def _matches_filters(event: dict, filters: WebhookFilters) -> bool:`
    - `def _seen_event_key(event: dict) -> str:`
    - `def _event_body(event: dict) -> bytes:`
- Tests available: `tests/integration/test_webhooks.py`,
  `tests/unit/test_typing_policy.py`, broad no-Docker unit suite.

Question: what is the minimal safe annotation plan? Please call out any risky
annotation choices to avoid, whether `FastAPI` is acceptable for `app`, and what
focused tests should be run. Keep this concise and actionable.
```
