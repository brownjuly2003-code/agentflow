"""Control-plane store port (ADR 0010).

The API process hosts a control plane — webhook delivery queue and attempt
log, alert rules/history, replay outbox, dead-letter transitions, usage
accounting — whose state must not live embedded per-pod once
``replicaCount > 1`` (ADR 0009). This port is the seam that makes the state
location swappable: an embedded DuckDB adapter is the single-replica default
profile; a PostgreSQL adapter is the scale profile (ADR 0010 rollout
slice 5).

Claim semantics are part of this contract, not adapter detail:

- ``enqueue_webhook_delivery`` returns ``True`` only when *this caller*
  inserted the row — inline delivery belongs to the enqueue winner alone, so
  a re-scan (or a second replica scanning the same journal) never re-POSTs a
  (webhook, event) that is already queued.
- ``claim_due_webhook_deliveries`` returns rows this worker now owns. The
  embedded adapter satisfies exclusivity degenerately (one process); the
  PostgreSQL adapter uses ``FOR UPDATE SKIP LOCKED`` plus a lease column so
  N replicas work-steal without leader election.

Rollout slice 1 covers the webhook delivery queue + attempt log. Slice 2
(this module's alert methods) covers the alert delivery/history log and the
alert-rule repository — including the rules' mutable runtime state (``state``,
``fired_at``, ``last_escalation_level``, flap window, cooldown), the sharpest
per-pod split-brain in the ADR's inventory. Outbox/dead-letter and usage
migrate behind this port in follow-up slices (see the ADR's rollout section).

The alert-rule repository methods (``load_alert_rules`` / ``save_alert_rules``)
operate on plain JSON-shaped ``dict`` records rather than the ``AlertRule``
pydantic model: the port must not import ``src.serving.api.alerts`` (that
module imports this one to resolve the store — see ``get_control_plane_store``
below), so callers validate/serialize at the boundary, exactly like the
embedded adapter's YAML round-trip already did before the port existed.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

CONTROL_PLANE_STORE_ENV = "AGENTFLOW_CONTROLPLANE_STORE"


@dataclass(frozen=True)
class WebhookQueueRow:
    """One durable (webhook, event) delivery owed to a receiver."""

    webhook_id: str
    event_id: str
    tenant: str | None
    event_type: str | None
    body: str | None


class ControlPlaneStore(ABC):
    """Port for control-plane state (ADR 0010). See the module docstring for
    the claim-semantics contract adapters must uphold."""

    # --- webhook durable delivery queue (re-drive state) ---------------------

    @abstractmethod
    def enqueue_webhook_delivery(
        self,
        *,
        webhook_id: str,
        event_id: str,
        tenant: str,
        event_type: str,
        body: str,
    ) -> bool:
        """Durably record a (webhook, event) delivery as ``pending``.

        Idempotent on ``(webhook_id, event_id)``; returns ``True`` only when a
        new row was inserted by this call (the caller may then inline-deliver).
        """

    @abstractmethod
    def claim_due_webhook_deliveries(self, *, limit: int) -> list[WebhookQueueRow]:
        """Return up to ``limit`` due ``pending`` deliveries this worker now
        owns, oldest first."""

    @abstractmethod
    def record_webhook_delivery_outcome(
        self,
        *,
        webhook_id: str,
        event_id: str,
        success: bool,
        status_code: int | None,
        error: str | None,
        max_attempts: int,
        backoff_seconds: Sequence[float],
    ) -> None:
        """Advance a queue row from one delivery round's outcome: success →
        ``delivered``; failure → bump attempts and re-schedule with backoff, or
        park as ``dead`` once ``max_attempts`` is reached."""

    @abstractmethod
    def park_webhook_delivery(self, *, webhook_id: str, event_id: str, error: str) -> None:
        """Park a queue row as ``dead`` (e.g. its webhook was removed or
        deactivated) so it is never re-driven again."""

    # --- webhook delivery attempt log (append-only) --------------------------

    @abstractmethod
    def log_webhook_delivery(
        self,
        *,
        delivery_id: str,
        webhook_id: str,
        event_id: str,
        event_type: str,
        attempt: int,
        status_code: int | None,
        success: bool,
        error: str | None,
    ) -> None:
        """Append one delivery attempt to the ``webhook_deliveries`` log."""

    @abstractmethod
    def get_webhook_delivery_logs(self, webhook_id: str, *, limit: int = 20) -> list[dict]:
        """Most recent attempt-log entries for one webhook, newest first.

        Safe to call from a worker thread (adapters isolate the read — the
        embedded store opens a dedicated cursor per call, audit_30 A2)."""

    # --- alert delivery history (append-only) --------------------------------

    @abstractmethod
    def log_alert_delivery(
        self,
        *,
        delivery_id: str,
        alert_id: str,
        alert_name: str,
        tenant: str,
        metric: str,
        current_value: float | None,
        previous_value: float | None,
        change_pct: float | None,
        threshold: float,
        condition: str,
        window: str,
        event_type: str,
        status_code: int | None,
        success: bool,
        error: str | None,
        payload: dict,
    ) -> None:
        """Append one alert-delivery attempt to the ``alert_history`` log."""

    @abstractmethod
    def get_alert_delivery_history(self, alert_id: str, *, limit: int = 20) -> list[dict]:
        """Most recent alert-history entries for one alert, newest first.

        Safe to call from a worker thread (adapters isolate the read — the
        embedded store opens a dedicated cursor per call, audit_30 A2)."""

    # --- alert rule repository (mutable runtime state) ------------------------

    @abstractmethod
    def load_alert_rules(self) -> list[dict]:
        """Return every alert rule as a JSON-shaped record (the caller
        validates each into ``AlertRule``), including mutable runtime state
        (``state``, ``fired_at``, ``last_escalation_level``, flap window)."""

    @abstractmethod
    def save_alert_rules(self, rules: list[dict]) -> None:
        """Persist the full alert-rule set verbatim (JSON-shaped records, the
        caller's serialized ``AlertRule.model_dump(mode="json")`` output)."""


def get_control_plane_store(app: FastAPI) -> ControlPlaneStore:
    """Resolve the app's control-plane store, creating the configured one on
    first use and caching it on ``app.state`` (the lazy pattern mirrors
    ``ensure_alert_dispatcher`` so lightweight test stubs keep working).

    ``AGENTFLOW_CONTROLPLANE_STORE`` selects the adapter. Fail-closed ratchet:
    ``postgres`` is the ADR 0010 target profile and raises until the
    ``PostgresControlPlaneStore`` adapter ships (rollout slice 5); anything
    else but ``embedded`` is a configuration error.
    """
    store: ControlPlaneStore | None = getattr(app.state, "control_plane_store", None)
    if store is not None:
        return store
    kind = (os.getenv(CONTROL_PLANE_STORE_ENV) or "embedded").strip().lower()
    if kind == "embedded":
        # Deferred: src.serving.api.alerts.dispatcher imports this module at
        # top level to resolve the store, so a module-level import here would
        # cycle. Resolved lazily, exactly like the EmbeddedControlPlaneStore
        # import above.
        from src.serving.api.alerts.dispatcher import get_alert_config_path

        from .embedded import EmbeddedControlPlaneStore

        # The one sanctioned reach into the engine's embedded connection: the
        # composition seam that binds the default profile's store to the
        # serving DuckDB. Everything above the port goes through the store.
        store = EmbeddedControlPlaneStore(
            conn_provider=lambda: app.state.query_engine._conn,
            alert_rules_path_provider=lambda: get_alert_config_path(app),
        )
    elif kind == "postgres":
        raise NotImplementedError(
            "AGENTFLOW_CONTROLPLANE_STORE=postgres is the ADR 0010 scale profile; "
            "the PostgresControlPlaneStore adapter ships in rollout slice 5 — "
            "until then only 'embedded' runs."
        )
    else:
        raise ValueError(
            f"Unknown control-plane store {kind!r} "
            f"(set {CONTROL_PLANE_STORE_ENV} to 'embedded', or leave it unset)."
        )
    app.state.control_plane_store = store
    return store
