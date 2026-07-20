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
covers the alert delivery/history log and the alert-rule repository —
including the rules' mutable runtime state (``state``, ``fired_at``,
``last_escalation_level``, flap window, cooldown), the sharpest per-pod
split-brain in the ADR's inventory. Slice 3 (this module's outbox/dead-letter
methods) covers the replay outbox and dead-letter status transitions,
preserving invariant 8 verbatim: ``mark_outbox_sent`` flips a delivered
outbox row *and* its dead-letter row to ``replayed`` in one transaction;
``schedule_outbox_retry`` flips both to ``failed`` once retries are exhausted,
in one transaction. Usage/sessions migrate behind this port in the next
slice (see the ADR's rollout section).

The alert-rule repository methods (``load_alert_rules`` / ``save_alert_rules``)
operate on plain JSON-shaped ``dict`` records rather than the ``AlertRule``
pydantic model: the port must not import ``src.serving.api.alerts`` (that
module imports this one to resolve the store — see ``get_control_plane_store``
below), so callers validate/serialize at the boundary, exactly like the
embedded adapter's YAML round-trip already did before the port existed. The
outbox/dead-letter methods follow the same rule for the same reason, and so
does the webhook-registration repository (slice 5, below).

Slice 5 ships the PostgreSQL adapter and closes the two per-pod gaps the
extraction slices left open:

- **Webhook registrations** (state class 5 of the ADR's inventory — the
  sharpest split-brain, a webhook registered on pod A that pod B has never
  heard of) move behind ``load_webhook_registrations`` /
  ``save_webhook_registrations``, mirroring the alert-rule repository: the
  embedded adapter keeps the byte-compatible per-app YAML file, the
  PostgreSQL adapter stores rows.
- **Alert tick single-flight** (``claim_alert_tick`` / ``complete_alert_tick``,
  ADR 0010 §2): the dispatcher claims each rule before evaluating it and
  completes the claim with that rule's advanced state. Rule state is
  persisted *per rule*, not as a full-set save — with per-rule claims, two
  replicas advancing different rules in overlapping ticks would clobber each
  other's runtime state through a full-set write.

The outbox/dead-letter write methods (``mark_outbox_sent``,
``schedule_outbox_retry``, ``enqueue_outbox_replay``,
``dismiss_dead_letter_event``) do NOT lazily create their tables on every
call, unlike the webhook/alert log methods above: ``OutboxProcessor`` and
``EventReplayer`` call ``ensure_outbox_schema`` once at construction (mirrors
the pre-port ``OutboxProcessor.__init__`` behavior verbatim). A lazy
``CREATE TABLE IF NOT EXISTS`` inside these methods would silently recreate a
table a test dropped mid-scenario to simulate a transaction failure,
defeating that fault injection.

Slice 4 covers API-usage accounting (``api_usage``: per-tenant/per-key
request counters, including the rotation status endpoint's "requests on the
old key" query) and API-session analytics (``api_sessions``: per-request
latency/entity/query telemetry powering the admin usage dashboards). Unlike
every store above, this state was NEVER on ``query_engine._conn`` — not even
in the outbox's ``:memory:`` special case — because ``AuthManager.db_path``
resolves to its own DuckDB file, independent of ``DUCKDB_PATH``, even when
the query engine runs on a file backend (see ``AuthManager.__init__``'s
sibling-path derivation). The embedded adapter preserves that separateness:
its usage/session methods open dedicated connections against
``usage_db_path_provider`` rather than the shared ``conn_provider``. The
scope turned out wider than "usage_table.py + analytics.py": ``KeyRotator``
(``key_rotation.py``) queries ``api_usage`` directly for old-key-usage
stats, and the admin dashboard (``admin_ui.py``) queries ``api_sessions``
directly for its QPS tile — both bypassed the port until this slice and are
covered here too, or a PostgreSQL swap (slice 5) would leave two call sites
still hard-wired to a local DuckDB file.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from fastapi import FastAPI

CONTROL_PLANE_STORE_ENV = "AGENTFLOW_CONTROLPLANE_STORE"
CONTROL_PLANE_PG_DSN_ENV = "AGENTFLOW_CONTROLPLANE_PG_DSN"


def control_plane_store_kind() -> str:
    """The configured adapter kind (``'embedded'`` when unset). Composition
    seams that must branch per profile (main.py deciding whether the
    outbox/auth consumers share the app-wide store) use this instead of
    re-parsing the env var."""
    return (os.getenv(CONTROL_PLANE_STORE_ENV) or "embedded").strip().lower()


@dataclass(frozen=True)
class WebhookQueueRow:
    """One durable (webhook, event) delivery owed to a receiver."""

    webhook_id: str
    event_id: str
    tenant: str | None
    event_type: str | None
    body: str | None


@dataclass(frozen=True)
class UsageRow:
    """One ``api_usage`` row owed for a served authenticated request."""

    tenant: str
    key_name: str
    endpoint: str
    key_id: str | None
    key_slot: str


@dataclass(frozen=True)
class OutboxEntry:
    """One pending replay-outbox row (a Kafka message owed to a topic)."""

    id: str
    event_id: str
    payload: object
    topic: str
    retry_count: int


@dataclass(frozen=True)
class TriageState:
    """One ``ops_exception_triage`` overlay row (ops-surfaces-spec.md §4.2) —
    control-plane state class 7. Only the ``webhook_delivery`` and
    ``reconciliation`` sources get overlay rows; dead-letter items are native
    and never tracked here (invariant I6)."""

    item_id: str
    tenant_id: str
    source: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    note: str | None


AUTO_RESOLVE_NOTE = "auto-resolved: no longer reproduces"
"""Sentinel ``note`` an auto-resolved overlay row carries (§4.2/§4.3) —
distinguishes a system-cleared finding from an operator's ``resolve`` call so
``count_triage_manual_actions`` counts only genuine human triage decisions
(the ``manual_resolutions`` KPI, §4.5)."""


def stuck_replay_threshold_seconds() -> float:
    """Staleness threshold for R2 ``stuck_replay`` (ops-surfaces-spec.md
    §4.3): "the control-plane lease interval; env-tunable". Reuses
    ``AGENTFLOW_CONTROLPLANE_LEASE_SECONDS`` — the same env var
    ``postgres.py``'s ``DEFAULT_CLAIM_LEASE_SECONDS`` reads for its claim
    leases — rather than a second knob; the embedded profile has no lease
    concept of its own but a replay can still get stuck locally (an inline
    ``EventReplayer.replay()`` that dies before its outbox entry resolves)."""
    lease_env = (os.getenv("AGENTFLOW_CONTROLPLANE_LEASE_SECONDS") or "").strip()
    if not lease_env:
        return 300.0
    try:
        return float(lease_env)
    except ValueError:
        raise ValueError(
            f"AGENTFLOW_CONTROLPLANE_LEASE_SECONDS must be a number of seconds, got {lease_env!r}."
        ) from None


class ControlPlaneStore(ABC):
    """Port for control-plane state (ADR 0010). See the module docstring for
    the claim-semantics contract adapters must uphold."""

    def ping(self) -> None:
        """Raise if the store is unreachable — cheap enough for a readiness probe.

        Concrete, not abstract: the embedded adapter lives on this process's own
        DuckDB and is up whenever the process is, so it needs no check. An
        adapter that talks to something over a network overrides this, and
        `/health/ready` reports a control plane it cannot reach instead of
        letting the replica take traffic it cannot serve (audit P0-3).
        """
        return None

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
        delivery_id: str | None = None,
    ) -> None:
        """Advance a queue row from one delivery round's outcome: success →
        ``delivered``; failure → bump attempts and re-schedule with backoff, or
        park as ``dead`` once ``max_attempts`` is reached.

        ``delivery_id`` makes the write **idempotent per delivery round**. The
        failure branch is a read-modify-write of ``attempts``; a store that
        retries this call after the DB committed but the commit-ack was lost
        (the PostgreSQL adapter's transient-error retry) would otherwise re-read
        the already-bumped ``attempts`` and bump it again — attempts+2, a
        premature dead-letter (P3). Adapters persist the last applied
        ``delivery_id`` on the queue row and no-op when it repeats, so the same
        round's outcome lands exactly once. ``None`` (a caller with no round id)
        keeps the pre-idempotency behaviour — every call applies."""

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

    # --- webhook registration repository --------------------------------------

    @abstractmethod
    def load_webhook_registrations(self) -> list[dict]:
        """Return every webhook registration as a JSON-shaped record (the
        caller validates each into ``WebhookRegistration``) — state class 5 of
        the ADR 0010 inventory, the per-pod YAML whose split-brain motivated
        the ADR. Same no-model rule as the alert-rule repository below: this
        module must not import ``webhook_dispatcher`` (it imports this one)."""

    @abstractmethod
    def save_webhook_registrations(self, registrations: list[dict]) -> None:
        """Persist the full registration set verbatim (JSON-shaped records,
        the caller's serialized ``WebhookRegistration.model_dump(mode="json")``
        output)."""

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

    @abstractmethod
    def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool:
        """Claim one alert rule's evaluation tick for this worker (ADR 0010
        §2): only the claim winner evaluates and pages; a lost claim means
        another pod owns this rule's tick, so N replicas never run N parallel
        state machines for the same rule. The embedded adapter grants every
        claim (one process); the PostgreSQL adapter takes a lease that expires
        on its own — crash recovery without coordination."""

    @abstractmethod
    def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None:
        """Release the rule's tick claim; when ``record`` is not ``None``,
        persist that rule's advanced runtime state in the same transaction as
        the release (ADR 0010 §2). ``record`` is the caller's serialized
        ``AlertRule.model_dump(mode="json")``, exactly like
        ``save_alert_rules`` — but scoped to one rule, so two replicas
        advancing different rules in overlapping ticks cannot clobber each
        other's state the way a full-set save would."""

    # --- replay outbox + dead-letter (invariant 8: one transaction) -----------

    @abstractmethod
    def ensure_outbox_schema(self) -> None:
        """Idempotently create the ``outbox`` and ``dead_letter_events``
        tables. Called once at ``OutboxProcessor`` / ``EventReplayer``
        construction — not lazily inside the methods below (see the module
        docstring)."""

    @abstractmethod
    def claim_due_outbox_entries(self, *, limit: int = 100) -> list[OutboxEntry]:
        """Return up to ``limit`` due ``pending`` outbox rows, oldest first."""

    @abstractmethod
    def get_pending_outbox_entry(self, outbox_id: str) -> OutboxEntry | None:
        """Fetch one ``pending`` outbox row by id, or ``None`` if it does not
        exist or has already left the ``pending`` state."""

    @abstractmethod
    def mark_outbox_sent(self, *, outbox_id: str, event_id: str) -> None:
        """Flip an outbox row to ``sent`` and its dead-letter row (if any) to
        ``replayed``, in one transaction (invariant 8). Rolls back and
        re-raises if either update fails."""

    @abstractmethod
    def schedule_outbox_retry(
        self,
        *,
        outbox_id: str,
        event_id: str,
        retry_count: int,
        error_message: str,
        max_retries: int,
    ) -> None:
        """Bump an outbox row's attempts and back off (exponential, floored at
        30s for Kafka-shaped errors), or park it ``failed`` and flip its
        dead-letter row to ``failed`` too once ``max_retries`` is reached —
        both updates in one transaction (invariant 8)."""

    @abstractmethod
    def enqueue_outbox_replay(
        self,
        *,
        outbox_id: str,
        event_id: str,
        payload: dict,
        topic: str,
        retry_count: int,
        replayed_at: datetime,
    ) -> None:
        """Mark a dead-letter row ``replay_pending`` (with the corrected
        payload and bumped retry count) and insert its outbox replay row, in
        one transaction (invariant 8, the other half of ``mark_outbox_sent``:
        this is the write ``EventReplayer.replay`` performs before inline
        delivery)."""

    @abstractmethod
    def get_dead_letter_event_for_replay(self, event_id: str) -> dict | None:
        """Fetch ``{event_id, payload, retry_count}`` for a replay/dismiss
        candidate, or ``None`` if the event does not exist."""

    @abstractmethod
    def dismiss_dead_letter_event(self, event_id: str) -> None:
        """Mark a dead-letter row ``dismissed``."""

    @abstractmethod
    def dead_letter_event_exists(self, event_id: str, tenant_id: str) -> bool:
        """Whether a dead-letter row exists for this event, scoped to
        ``tenant_id`` (write-access and tenant-isolation gate)."""

    @abstractmethod
    def get_dead_letter_event(self, event_id: str, tenant_id: str) -> dict | None:
        """Full detail record for one dead-letter event, tenant-scoped, or
        ``None`` if not found. ``payload`` is returned as stored (string or
        dict) — the caller decodes it."""

    @abstractmethod
    def list_dead_letter_events(
        self,
        *,
        tenant_id: str,
        reason: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        """Paginated ``failed`` dead-letter events for one tenant (optionally
        filtered by ``failure_reason``), newest first, plus the total count
        matching the filter."""

    @abstractmethod
    def get_dead_letter_stats(self, tenant_id: str) -> dict:
        """``{"counts": {reason: count}, "last_24h": int, "trend": [...]}``
        for one tenant's active (``failed``) dead-letter events."""

    @abstractmethod
    def list_dead_letter_events_for_inbox(
        self, tenant_id: str, *, limit: int | None = None
    ) -> list[dict]:
        """Every dead-letter row for one tenant, any status, newest first —
        the exception inbox's native source (§4.1 #1). Unlike
        ``list_dead_letter_events`` (the public ``/v1/deadletter`` route:
        ``status='failed'`` only, paginated), the inbox aggregates and
        paginates across three heterogeneous sources itself. ``limit`` bounds
        the read to the newest N rows (S-8) — the inbox probes with
        ``cap + 1`` to detect truncation instead of cutting silently."""

    @abstractmethod
    def list_stuck_replay_dead_letter_events(
        self, tenant_id: str, *, older_than_seconds: float
    ) -> list[dict]:
        """``replay_pending`` dead-letter rows whose ``last_retried_at`` is
        older than ``older_than_seconds`` — R2 ``stuck_replay`` (§4.3): a
        replay was requested but its outbox entry never completed the
        invariant-8 flip."""

    @abstractmethod
    def count_dead_letter_manual_actions(self, tenant_id: str) -> int:
        """Count of ``replayed``/``dismissed`` dead-letter rows for one
        tenant — the native half of the ``manual_resolutions`` KPI (§4.5).
        Dismissal carries no per-action timestamp in this schema, so this is
        a cumulative count, not time-windowed — an honest limitation, not
        faked precision."""

    # --- exception-inbox triage overlay (control-plane state class 7) --------

    @abstractmethod
    def ensure_triage_schema(self) -> None:
        """Idempotently create the ``ops_exception_triage`` table."""

    @abstractmethod
    def list_triage_states(self, *, tenant_id: str, source: str | None = None) -> list[TriageState]:
        """Every overlay row for one tenant, optionally filtered by
        ``source`` (``'webhook_delivery'`` or ``'reconciliation'``)."""

    @abstractmethod
    def upsert_triage_finding(
        self, *, item_id: str, tenant_id: str, source: str, seen_at: datetime
    ) -> None:
        """Insert an ``open`` row for a first-seen finding, or refresh
        ``last_seen_at`` for one already ``open``/``acknowledged``. A row an
        operator resolved stays ``resolved`` unless ``seen_at`` is after its
        ``resolved_at`` — the finding reproducing post-resolution reopens it
        as ``open`` with a fresh ``last_seen_at`` (§4.2)."""

    @abstractmethod
    def auto_resolve_missing_triage_findings(
        self,
        *,
        tenant_id: str,
        source: str,
        seen_item_ids: Sequence[str],
        resolved_at: datetime,
    ) -> None:
        """Resolve every non-``resolved`` overlay row of ``source``
        (tenant-scoped) whose ``item_id`` is absent from ``seen_item_ids`` —
        the finding no longer reproduces this run (§4.2/§4.3), noted
        ``'auto-resolved: no longer reproduces'``."""

    @abstractmethod
    def set_triage_state(
        self, *, item_id: str, tenant_id: str, status: str, note: str | None = None
    ) -> bool:
        """Set one overlay row's status (``'acknowledged'`` or
        ``'resolved'``), stamping ``resolved_at`` when resolving — one
        transactional ``UPDATE`` (single-row, so DuckDB's autocommit and a
        PostgreSQL connection's implicit transaction both satisfy this
        without extra ceremony). Returns ``False`` if no row exists for
        ``(item_id, tenant_id)`` — the caller 404s; this method never creates
        a row (only ``upsert_triage_finding`` does, from a live detection)."""

    @abstractmethod
    def count_triage_manual_actions(self, tenant_id: str) -> int:
        """Count of overlay rows in ``acknowledged``/``resolved`` status for
        one tenant — the overlay half of the ``manual_resolutions`` KPI
        (§4.5)."""

    # --- webhook dead deliveries for the exception inbox ----------------------

    @abstractmethod
    def list_dead_webhook_deliveries(
        self, tenant_id: str | None = None, *, limit: int | None = None
    ) -> list[dict]:
        """Every ``webhook_delivery_queue`` row parked ``dead``, optionally
        scoped to one tenant — the exception inbox's overlay source #2
        (§4.1). ``limit`` bounds the read to the newest N rows (S-8), same
        ``cap + 1`` probe contract as the dead-letter inbox read."""

    # --- API usage accounting (per-tenant/per-key request counters) ----------

    @abstractmethod
    def ensure_usage_schema(self) -> None:
        """Idempotently create the ``api_usage`` table. Called once at
        ``AuthManager`` construction — not lazily inside the methods below
        (mirrors the pre-port ``ensure_usage_table`` call site, main.py's
        lifespan, verbatim)."""

    @abstractmethod
    def record_api_usage(
        self,
        *,
        tenant: str,
        key_name: str,
        endpoint: str,
        key_id: str | None,
        key_slot: str,
    ) -> None:
        """Append one ``api_usage`` row for a completed authenticated
        request. Raises on exhausted retries — a caller (``record_usage``)
        depends on the exception to skip its post-insert audit publish.

        The exception stops there: the usage writer catches it, increments
        ``agentflow_usage_record_failures_total`` and drops the row.
        Accounting is a side-channel and must not fail the request it was
        counting."""

    def record_api_usage_batch(self, rows: Sequence[UsageRow]) -> None:
        """Append many ``api_usage`` rows as **one** unit of work.

        A backend that pays a per-commit cost (an fsync, a round trip) should
        override this so a batch costs one, not ``len(rows)``. The embedded
        DuckDB store does; without it the accounting throughput ceiling is
        ``1 / commit_latency`` rows per second, which on a slow disk is below
        the request rate the API can otherwise serve (2026-07-09).

        Same failure contract as ``record_api_usage``: raise, and the caller
        drops the batch and counts it.
        """
        for row in rows:
            self.record_api_usage(
                tenant=row.tenant,
                key_name=row.key_name,
                endpoint=row.endpoint,
                key_id=row.key_id,
                key_slot=row.key_slot,
            )

    @abstractmethod
    def get_usage_by_tenant(self) -> list[dict]:
        """``{"tenant": ..., "requests_last_24h": ...}`` per tenant."""

    @abstractmethod
    def get_usage_by_key(self) -> dict[tuple[str, str], int]:
        """``{(tenant, key_name): requests_last_24h}`` for every active key."""

    @abstractmethod
    def get_old_key_usage_by_key_id(self) -> dict[str, int]:
        """``{key_id: requests_last_hour}`` for requests served on a
        rotated-out (``previous``) key slot — powers the rotation-status
        endpoint's "requests on the old key" figure."""

    # --- API session analytics (per-request latency/entity/query log) -------

    @abstractmethod
    def record_api_session(self, request_id: str, record: dict) -> None:
        """Insert-or-replace one ``api_sessions`` row, keyed on
        ``request_id`` (idempotent — a retried background write must not
        double-count). Best-effort: logs and returns on exhausted retries
        rather than raising, unlike ``record_api_usage``."""

    @abstractmethod
    def get_usage_analytics(self, *, window: str = "24h", tenant: str | None = None) -> dict:
        """Per-tenant request volume/error-rate/cache-hit-rate/latency and
        top endpoints over ``window`` (e.g. ``"15m"``, ``"1h"``, ``"7d"``)."""

    @abstractmethod
    def get_top_queries(self, *, limit: int = 10, window: str = "24h") -> dict:
        """Most frequent ``/v1/query`` question texts over ``window``."""

    @abstractmethod
    def get_top_entities(self, *, limit: int = 10, window: str = "24h") -> dict:
        """Most frequently fetched ``(entity_type, entity_id)`` pairs over
        ``window``."""

    @abstractmethod
    def get_latency_analytics(self, *, window: str = "24h") -> dict:
        """Per-endpoint request count and p50/p95/p99 latency over
        ``window``."""

    @abstractmethod
    def get_anomalies(self, *, window: str = "24h") -> dict:
        """Per-tenant hours whose request volume spikes >3x their own
        historical hourly average within ``window``."""

    @abstractmethod
    def get_queries_per_second_last_minute(self) -> float:
        """Average QPS over the trailing 60s of ``api_sessions`` rows —
        powers the admin-UI live dashboard tile."""


def get_control_plane_store(app: FastAPI) -> ControlPlaneStore:
    """Resolve the app's control-plane store, creating the configured one on
    first use and caching it on ``app.state`` (the lazy pattern mirrors
    ``ensure_alert_dispatcher`` so lightweight test stubs keep working).

    ``AGENTFLOW_CONTROLPLANE_STORE`` selects the adapter: ``embedded``
    (default) or ``postgres`` (scale profile, slice 5 — requires
    ``AGENTFLOW_CONTROLPLANE_PG_DSN`` and the optional ``psycopg``
    dependency; both fail the boot loudly when missing, never a silent
    fallback to embedded). Anything else is a configuration error.
    """
    store: ControlPlaneStore | None = getattr(app.state, "control_plane_store", None)
    if store is not None:
        return store
    kind = control_plane_store_kind()
    if kind == "embedded":
        # Deferred: src.serving.api.alerts.dispatcher and webhook_dispatcher
        # import this module at top level to resolve the store, so module-level
        # imports here would cycle. Resolved lazily, exactly like the
        # EmbeddedControlPlaneStore import above.
        from src.serving.api.alerts.dispatcher import get_alert_config_path
        from src.serving.api.webhook_dispatcher import get_webhook_config_path

        from .embedded import EmbeddedControlPlaneStore

        # The one sanctioned reach into the engine's embedded connection: the
        # composition seam that binds the default profile's store to the
        # serving DuckDB. Everything above the port goes through the store.
        store = EmbeddedControlPlaneStore(
            conn_provider=lambda: app.state.query_engine._conn,
            alert_rules_path_provider=lambda: get_alert_config_path(app),
            webhook_registrations_path_provider=lambda: get_webhook_config_path(app),
        )
    elif kind == "postgres":
        # Deferred for a different reason than the embedded branch: psycopg is
        # an optional dependency (the redis pattern), so the adapter module
        # must not load unless this profile is actually configured.
        from .postgres import resolve_postgres_store_from_env

        store = resolve_postgres_store_from_env()
    else:
        raise ValueError(
            f"Unknown control-plane store {kind!r} "
            f"(set {CONTROL_PLANE_STORE_ENV} to 'embedded', or leave it unset)."
        )
    app.state.control_plane_store = store
    return store
