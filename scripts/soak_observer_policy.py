"""Abort-decision policy for golden-soak observers.

Extracted after the soak ``-01``..``-05`` RCA
(docs/perf/golden-4h-soak-failures-01-05-rca-2026-08-09.md) so the racing
health surfaces produce one attributable first reason:

- a **terminal** Flink job state decides immediately (no streak) — in ``-05``
  the terminal ``FAILED`` had to wait for a five-sample streak while a
  two-sample pod-topology race stored a downstream symptom as the reason;
- Kubernetes **API observation failures** can only ever abort as
  ``pods_api_unhealthy`` — in ``-01``/``-02`` two transport errors were
  stored as a pod-topology abort while the pods were fine;
- when Flink degraded **before** the pod topology changed, the abort is
  attributed to Flink (``flink_led_topology_loss``), not to the newer
  topology symptom.

Runtime soak packs embed or import this module; it is pure state-machine
logic with no I/O so the contract stays unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

API_TRANSPORT_ERRORS = frozenset({"TimeoutError", "URLError", "HTTPError", "OSError", "SSLError"})
TERMINAL_JOB_STATES = frozenset({"FAILED"})


@dataclass(frozen=True)
class FlinkSample:
    """One observer sample of the Flink job health surface."""

    ok: bool
    job_state: str | None
    tasks_running: int
    tasks_total: int
    tasks_all_running: bool
    error: str | None = None


@dataclass(frozen=True)
class PodsSample:
    """One observer sample of the JM/TM pod surface."""

    ok: bool
    api_error: str | None
    ready_count: int
    total_count: int
    all_running_ready: bool
    restart_total: int


@dataclass(frozen=True)
class AbortDecision:
    """First fail-closed reason; frozen once made."""

    reason_class: str
    detail: str


class FlinkPodsAbortPolicy:
    """Streak bookkeeping plus precedence for the racing health surfaces.

    Precedence per sample: terminal Flink state > Flink unhealthy streak >
    pod restart budget > API observation streak > pod topology streak. A
    topology-triggered abort is re-attributed to Flink when the Flink bad
    streak is at least as old as the topology streak.
    """

    def __init__(
        self,
        *,
        expected_pods: int,
        max_pod_restarts: int,
        api_streak_need: int,
        flink_streak_need: int,
        topology_streak_need: int,
    ) -> None:
        self._expected_pods = expected_pods
        self._max_pod_restarts = max_pod_restarts
        self._api_streak_need = api_streak_need
        self._flink_streak_need = flink_streak_need
        self._topology_streak_need = topology_streak_need
        self._flink_bad_streak = 0
        self._api_bad_streak = 0
        self._topology_bad_streak = 0
        self._decision: AbortDecision | None = None

    @property
    def decision(self) -> AbortDecision | None:
        return self._decision

    def observe(self, flink: FlinkSample, pods: PodsSample) -> AbortDecision | None:
        if self._decision is not None:
            return self._decision

        flink_bad = (
            (not flink.ok) or str(flink.job_state or "") != "RUNNING" or not flink.tasks_all_running
        )
        self._flink_bad_streak = self._flink_bad_streak + 1 if flink_bad else 0

        api_err = bool(pods.api_error) or (
            (not pods.ok) and str(pods.api_error or "") in API_TRANSPORT_ERRORS
        )
        if api_err:
            # Topology is unobservable this sample: freeze its streak.
            self._api_bad_streak += 1
        else:
            self._api_bad_streak = 0
            topology_bad = (not pods.ok) or (
                pods.total_count != self._expected_pods
                or pods.ready_count != self._expected_pods
                or not pods.all_running_ready
            )
            self._topology_bad_streak = self._topology_bad_streak + 1 if topology_bad else 0

        flink_context = (
            f"flink_state={flink.job_state} "
            f"tasks={flink.tasks_running}/{flink.tasks_total} "
            f"flink_error={flink.error}"
        )
        pods_context = (
            f"pods_ready={pods.ready_count}/{pods.total_count} pods_error={pods.api_error}"
        )

        if str(flink.job_state or "") in TERMINAL_JOB_STATES:
            return self._decide("flink_terminal", f"{flink_context} {pods_context}")

        if self._flink_bad_streak >= self._flink_streak_need:
            return self._decide(
                "flink_unhealthy",
                f"{flink_context} streak={self._flink_bad_streak} {pods_context}",
            )

        if pods.ok and pods.restart_total > self._max_pod_restarts:
            return self._decide(
                "pod_restart_budget",
                f"pod_restarts={pods.restart_total} max={self._max_pod_restarts} {flink_context}",
            )

        if self._api_bad_streak >= self._api_streak_need:
            return self._decide(
                "pods_api_unhealthy",
                f"{pods_context} streak={self._api_bad_streak} {flink_context}",
            )

        if self._topology_bad_streak >= self._topology_streak_need:
            if self._flink_bad_streak >= self._topology_bad_streak:
                return self._decide(
                    "flink_led_topology_loss",
                    f"{flink_context} flink_streak={self._flink_bad_streak} "
                    f"{pods_context} topology_streak={self._topology_bad_streak}",
                )
            return self._decide(
                "pod_topology_unhealthy",
                f"{pods_context} streak={self._topology_bad_streak} {flink_context}",
            )

        return None

    def _decide(self, reason_class: str, detail: str) -> AbortDecision:
        self._decision = AbortDecision(reason_class=reason_class, detail=detail)
        return self._decision
