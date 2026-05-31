# Second opinion prompt: alerts dispatcher strict mypy slice

Status: blocked on 2026-06-01 because `claude -p` returned:

```text
API Error: The socket connection was closed unexpectedly. For more information, pass `verbose: true` in the second argument to fetch()
SessionEnd hook [node "${CLAUDE_PLUGIN_ROOT}/scripts/session-lifecycle-hook.mjs" SessionEnd] failed: Hook cancelled
```

No code changes were made for this slice.

## Prompt

```text
You are the required second opinion for a narrow strict-mypy slice in D:\DE_project.

Goal: add disallow_untyped_defs=true for module src.serving.api.alerts.dispatcher with the smallest safe code change.

Current facts:
- Python/FastAPI project. Existing mypy config currently only enforces disallow_untyped_defs for selected modules, not disallow_any_generics.
- src/serving/api/alerts/dispatcher.py has 2 public untyped function signatures in the AST baseline, but strict mypy will check all defs in the module.
- Key currently untyped FastAPI app boundaries:
  * def get_alert_config_path(app) -> Path
  * def ensure_alert_dispatcher(app) -> AlertDispatcher
  * class AlertDispatcher: def __init__(self, app, poll_interval_seconds: float = 60.0) -> None
- The module uses getattr(app.state, "alert_config_path", None) and app.state.alert_dispatcher, and many methods import from src.serving.api import alert_dispatcher as compat so tests can monkeypatch datetime/logger/httpx. I should not refactor those compatibility imports.
- Other signatures include def update_alert(..., updates: dict) -> AlertRule | None and async def send_test_alert(...) -> dict. Because disallow_any_generics is not enabled, I think these do not need narrowing for this slice.
- Planned policy test: assert "src.serving.api.alerts.dispatcher" is in _strict_modules().
- Planned verification: mypy src, focused alert tests, OpenAPI check, ruff, no-Docker unit suite, git diff --check.

Question: Is the minimal safe implementation just importing fastapi.FastAPI and annotating the three app parameters above as FastAPI, then adding the strict mypy override? Are there any mypy/behavior risks or smaller/better annotations I should use for this slice?
```
