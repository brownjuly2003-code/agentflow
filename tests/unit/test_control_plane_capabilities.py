from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.serving.control_plane import ControlPlaneStore
from src.serving.control_plane.capabilities import (
    AlertRepository,
    OutboxReplayRepository,
    UsageAuditRepository,
    WebhookRepository,
    get_alert_repository,
    get_outbox_replay_repository,
    get_usage_audit_repository,
    get_webhook_repository,
)
from src.serving.control_plane.embedded import EmbeddedControlPlaneStore
from src.serving.control_plane.postgres import PostgresControlPlaneStore

CAPABILITIES = (
    WebhookRepository,
    AlertRepository,
    OutboxReplayRepository,
    UsageAuditRepository,
)


@pytest.mark.parametrize(
    "adapter",
    [EmbeddedControlPlaneStore, PostgresControlPlaneStore],
)
def test_both_adapters_conform_to_every_capability(adapter: type[ControlPlaneStore]) -> None:
    for capability in CAPABILITIES:
        assert issubclass(adapter, capability)


def test_capabilities_cover_the_wide_facade_without_exposing_it_to_consumers() -> None:
    capability_methods = {
        name
        for capability in CAPABILITIES
        for name in capability.__dict__
        if not name.startswith("_")
    }

    assert set(ControlPlaneStore.__abstractmethods__) <= capability_methods
    assert all(
        len({name for name in capability.__dict__ if not name.startswith("_")})
        < len(ControlPlaneStore.__abstractmethods__)
        for capability in CAPABILITIES
    )


def test_app_repository_resolvers_return_narrow_views_of_same_store() -> None:
    store = SimpleNamespace()
    app = SimpleNamespace(state=SimpleNamespace(control_plane_store=store))

    assert get_webhook_repository(app) is store
    assert get_alert_repository(app) is store
    assert get_outbox_replay_repository(app) is store
    assert get_usage_audit_repository(app) is store
