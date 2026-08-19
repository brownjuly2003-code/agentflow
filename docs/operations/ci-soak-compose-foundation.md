# CI soak Compose foundation: current state and next-session handoff

**Last updated:** 2026-08-19

**Status:** foundation committed; runtime execution is not implemented

**Foundation commit:** `9dffe47` (`feat(ops): add CI soak Compose foundation`)

## Read this first

- The repository contains a tracked source pack and a Docker Compose topology.
- It does not contain a CI workflow, runtime harness, Kubernetes-pods
  compatibility shim, lifecycle controller, or PASS publisher.
- No container was built or started while the foundation was implemented.
- A successful Compose configuration check is not a soak result.
- The future CI result is a separate capacity-independent
  traffic/exactness/Flink-quiet gate. It does not close the Mac
  kind/operator/HA/Helm-rollback gate.
- No push is authorized or implied by this document.

This document is the canonical tracked handoff for the CI Compose path. Local
artifacts under `.codex-grok-tasks/` remain useful provenance, but their old
HEAD values, ahead counts, and design-only blocker lists are not current state.
Always trust the current Git state and the tracked contracts listed below.

## Current state

| Item | State | Evidence and meaning |
| --- | --- | --- |
| Eight-file source pack | Tracked, immutable reference | `scripts/golden_soak/pack/`; byte sizes and SHA-256 values are pinned by `MANIFEST.json` and the unit contract |
| Source identity | `20260819-07` | The manifest labels it `source-reference-only` |
| Compose topology | Tracked, configuration-validated | `docker-compose.soak.yml`, merged with the base and Flink Compose files |
| Foundation contract | Green at commit time | `tests/unit/test_ci_soak_foundation.py`: 6 tests passed |
| Runtime harness | Missing | Nothing currently drives baseline, observer, producer, verifier, evidence capture, or cleanup |
| Kubernetes-pods shim | Missing | The byte-identical verifier still needs a compatible view of exactly one JobManager and one TaskManager |
| CI workflow | Missing | No workflow dispatch, timeout, cancellation, artifact upload, or runner budget gate exists |
| Runtime proof | Not attempted | Images, health checks, traffic, exactness, disk use, and duration remain unproven |
| Push or remote mutation | Not performed | The foundation and this handoff are local commits until separately authorized |

The copied eight-file subset is not a complete Mac runtime pack. It excludes
the launch and recovery scripts affected by the later stamper correction in
`3504c72`. Do not use it to create or rerun a Mac soak identity. A future Mac
identity must be generated with the stamper at or after `3504c72`.

## Landed topology contract

The overlay defines only these services:

- `kafka`, `soak-topics-init`, and `clickhouse`;
- `flink-jobmanager`, one `flink-taskmanager`, and `flink-job-runner`;
- `iceberg-rest`, `iceberg-init`, and `lake-materializer`;
- `serving-init`, `serving-bridge`, and `agentflow-api`.

It intentionally omits Redis, PostgreSQL, Prometheus, and Grafana. The only
overlay-owned volume is `soak-api-data`.

The important dependency edges are:

```text
kafka-init -> soak-topics-init -> flink-job-runner
minio-init -> iceberg-rest -> iceberg-init -> lake-materializer
clickhouse -> serving-init -> agentflow-api
                           -> serving-bridge
```

The foundation also fixes four design hazards before any runtime attempt:

1. Flink uses one TaskManager because the verifier expects exactly two healthy
   Flink containers in total: JobManager plus TaskManager.
2. The fresh CI consumer group starts with `earliest-offset`; it does not rely
   on pre-seeded group offsets.
3. `orders.status` is created before `flink-job-runner` starts.
4. `iceberg-init` waits for the REST catalog and completes before
   `lake-materializer` starts.

All three Flink services carry the same checkpoint and bounded restart policy:

| Variable | Value |
| --- | --- |
| `FLINK_CHECKPOINT_INTERVAL_MS` | `10000` |
| `FLINK_CHECKPOINT_MIN_PAUSE_MS` | `10000` |
| `FLINK_RESTART_MAX_FAILURES_PER_INTERVAL` | `3` |
| `FLINK_RESTART_FAILURE_RATE_INTERVAL_MS` | `300000` |
| `FLINK_RESTART_DELAY_MS` | `10000` |
| `AGENTFLOW_FLINK_GROUP_ID` | `agentflow-ci-soak-stream` |
| `AGENTFLOW_KAFKA_STARTUP_MODE` | `earliest-offset` |
| `FLINK_PARALLELISM` | `2` |

## Verification evidence

The implementation session used a RED-to-GREEN contract. Before the files
existed, all six foundation tests failed. After implementation and one narrow
manifest correction, the final evidence was:

- `python -m pytest tests/unit/test_ci_soak_foundation.py -q` — `6 passed`;
- Ruff check and format check — passed;
- `py_compile` for the new unit contract — passed;
- merged Compose `config --quiet` — passed;
- byte size and SHA-256 checks for all eight pack files — passed;
- LF/NUL and known-secret-pattern scans for all 12 foundation files — passed;
- exact staged-path comparison and `git diff --cached --check` — passed.

Revalidate the current configuration without starting services:

```powershell
python -m pytest tests/unit/test_ci_soak_foundation.py -q
docker compose -f docker-compose.yml -f docker-compose.flink.yml -f docker-compose.soak.yml config --quiet
```

These commands prove only the tracked foundation contract and the merged
Compose model. They do not prove image buildability, service readiness,
container continuity, traffic delivery, exactness, four-hour stability, or
rollback behavior.

## Gate semantics

A future CI PASS must remain fail-closed. At minimum, it must bind one runtime
identity to all of the following evidence:

- producer final result is PASS, delivered count equals the requested count,
  and failures equal zero;
- observer never emits ABORT and reaches its final PASS state;
- the byte-identical verifier returns PASS;
- the JobManager and TaskManager identities remain attributable across the
  run, so a short unnoticed resubmit cannot be mistaken for quiet continuity;
- final evidence and the terminal result survive failure or cancellation.

Even when all of those conditions are implemented and observed, the result is
only the capacity-independent CI gate. The Mac operator/HA/rollback work stays
open; see `docs/perf/golden-operator-acceptance-2026-07-30.md` and
`docs/perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md`.

## Recommended next-session sequence

Only the first item is the next named implementation slice. Keep later items
separate so a green focused gate ends each turn.

1. **Local runtime harness contract — next slice.** Add RED tests, then
   implement a fail-closed harness and the verifier-compatible pods shim. It
   must preserve the eight pack files byte for byte, validate their manifest
   before use, enforce the dependency/start order, track JobManager and
   TaskManager identity, write bounded evidence, and perform cleanup. Do not
   add a workflow or run the four-hour soak in this slice.
2. **Short local rehearsal — later slice.** After explicit runtime scope is
   confirmed, run a small-count rehearsal to prove image build, readiness,
   traffic, verifier compatibility, disk headroom, evidence, and cleanup. A
   rehearsal result must not be labelled a soak PASS.
3. **Workflow wiring — later slice.** Add dispatch inputs, a hard timeout,
   `cancel-in-progress: false`, fail-closed finalization, and always-uploaded
   artifacts. This still does not authorize a push.
4. **Remote rehearsal and full run — external gates.** Require explicit push
   authorization, inspect current GitHub runner limits and free disk, dispatch
   the short rehearsal first, and attempt the full run only after its evidence
   is accepted.

## Next-session entry checklist

1. Check the latest user message for stop or process-frustration triggers.
2. Run `git status --short` and inspect the current `HEAD`; do not rely on an
   old ahead count in local notes.
3. Read this document, `scripts/golden_soak/README.md`, and
   `tests/unit/test_ci_soak_foundation.py`.
4. Preserve unrelated dirty and untracked files.
5. Do not modify the eight files under `scripts/golden_soak/pack/`.
6. Keep runtime, workflow, push, and Mac-gate claims outside the next slice
   unless the user explicitly expands its scope.

## Tracked file map

- `docker-compose.soak.yml` — foundation overlay.
- `scripts/golden_soak/MANIFEST.json` — pack provenance and integrity.
- `scripts/golden_soak/README.md` — fail-closed pack boundary.
- `scripts/golden_soak/pack/` — immutable eight-file source reference.
- `tests/unit/test_ci_soak_foundation.py` — executable foundation contract.
- `docs/operations/ci-soak-compose-foundation.md` — this canonical handoff.
