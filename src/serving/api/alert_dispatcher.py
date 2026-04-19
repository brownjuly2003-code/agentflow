from __future__ import annotations

from datetime import datetime

import httpx
import structlog

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

logger = structlog.get_logger()

__all__ = [
    "DEFAULT_ALERTS_CONFIG_PATH",
    "AlertConfig",
    "AlertDispatcher",
    "AlertEscalationStep",
    "AlertFlapDetection",
    "AlertRule",
    "create_alert",
    "datetime",
    "deactivate_alert",
    "ensure_alert_dispatcher",
    "ensure_alert_history_table",
    "get_alert",
    "get_alert_config_path",
    "get_alert_history",
    "httpx",
    "list_alerts",
    "load_alerts",
    "logger",
    "save_alerts",
    "update_alert",
]
