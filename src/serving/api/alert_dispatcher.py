"""Backwards-compatible re-export of the alerts public API.

Historical import path ``src.serving.api.alert_dispatcher`` kept for
``main.py``/routers. The clock, logger, and HTTP client live in their
defining modules (``alerts.dispatcher``/``alerts.escalation``/``alerts.history``)
and are patched there in tests — this module no longer tunnels them.
"""

from __future__ import annotations

from src.serving.api.alerts import (
    DEFAULT_ALERTS_CONFIG_PATH,
    AlertConfig,
    AlertDispatcher,
    AlertEscalationStep,
    AlertFlapDetection,
    AlertRule,
    create_alert,
    deactivate_alert,
    ensure_alert_dispatcher,
    ensure_alert_history_table,
    get_alert,
    get_alert_config_path,
    get_alert_history,
    list_alerts,
    load_alerts,
    save_alerts,
    update_alert,
)

__all__ = [
    "DEFAULT_ALERTS_CONFIG_PATH",
    "AlertConfig",
    "AlertDispatcher",
    "AlertEscalationStep",
    "AlertFlapDetection",
    "AlertRule",
    "create_alert",
    "deactivate_alert",
    "ensure_alert_dispatcher",
    "ensure_alert_history_table",
    "get_alert",
    "get_alert_config_path",
    "get_alert_history",
    "list_alerts",
    "load_alerts",
    "save_alerts",
    "update_alert",
]
