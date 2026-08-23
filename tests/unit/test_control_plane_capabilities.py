from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentflow_runtime.serving.control_plane import ControlPlaneStore
from agentflow_runtime.serving.control_plane.capabilities import (
    AlertRepository,
    OutboxReplayRepository,
    UsageAuditRepository,
    WebhookRepository,
    get_alert_repository,
    get_outbox_replay_repository,
    get_usage_audit_repository,
    get_webhook_repository,
)
from agentflow_runtime.serving.control_plane.embedded import EmbeddedControlPlaneStore
from agentflow_runtime.serving.control_plane.postgres import PostgresControlPlaneStore

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


def _home_suffix(adapter: type, name: str, prefix: str) -> str:
    """The capability-module suffix (``webhook``, ``alert``, ...) whose
    repository class defines ``name`` for this adapter family."""
    for klass in adapter.__mro__:
        if name in klass.__dict__:
            module = klass.__module__.rsplit(".", 1)[-1]
            assert module.startswith(prefix), (
                f"{adapter.__name__}.{name} resolves outside the {prefix}* "
                f"capability repositories: {module}"
            )
            return module.removeprefix(prefix)
    raise AssertionError(f"{adapter.__name__} does not define {name}")


def test_capability_methods_live_in_matching_bounded_repositories() -> None:
    # Audit F-08: the two adapters must evolve in sync, and review/mutation
    # locality comes from each capability method living in its bounded
    # repository module. Every port method must resolve inside a capability
    # repository (never the assembly facade), and the embedded and PostgreSQL
    # implementations of one method must live in same-named modules.
    for name in sorted(ControlPlaneStore.__abstractmethods__):
        embedded_home = _home_suffix(EmbeddedControlPlaneStore, name, "embedded_")
        postgres_home = _home_suffix(PostgresControlPlaneStore, name, "postgres_")
        assert embedded_home == postgres_home, (
            f"{name} drifted: embedded_{embedded_home} vs postgres_{postgres_home}"
        )


def test_app_repository_resolvers_return_narrow_views_of_same_store() -> None:
    store = SimpleNamespace()
    app = SimpleNamespace(state=SimpleNamespace(control_plane_store=store))

    assert get_webhook_repository(app) is store
    assert get_alert_repository(app) is store
    assert get_outbox_replay_repository(app) is store
    assert get_usage_audit_repository(app) is store
