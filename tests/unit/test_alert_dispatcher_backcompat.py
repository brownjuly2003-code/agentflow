from src.serving.api import alert_dispatcher
from src.serving.api.alerts import (
    AlertDispatcher,
    create_alert,
    ensure_alert_dispatcher,
    get_alert_history,
)


def test_alert_dispatcher_keeps_backwards_compatible_exports():
    assert alert_dispatcher.AlertDispatcher is AlertDispatcher
    assert alert_dispatcher.create_alert is create_alert
    assert alert_dispatcher.ensure_alert_dispatcher is ensure_alert_dispatcher
    assert alert_dispatcher.get_alert_history is get_alert_history
