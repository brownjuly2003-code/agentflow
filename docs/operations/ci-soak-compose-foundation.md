# CI soak Compose foundation and runtime harness: current state and handoff

**Last updated:** 2026-08-19

**Status:** foundation and fail-closed runtime contract committed; Mac host
preflight complete; live rehearsal blocked on authorized source delivery

**Foundation commit:** `9dffe47` (`feat(ops): add CI soak Compose foundation`)

**Runtime contract commit:** `45817b1` (`feat(ops): add fail-closed CI soak runtime harness`)

## Read this first

- The repository contains a tracked source pack, a Docker Compose topology, a
  local runtime controller, and an identity-bound Kubernetes-pods shim.
- It does not contain a CI workflow, and the new controller has not been run
  against live containers.
- No container was built or started while either implementation slice was
  developed and verified.
- A read-only Mac host preflight found a ready Docker daemon and sufficient
  disk, but the permitted Mac checkout does not contain the runtime commits or
  files. No source was copied and no remote checkout was changed.
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
| Runtime harness | Implemented, not rehearsed | `scripts/golden_soak/runtime.py` validates the complete pack before Docker, refuses pre-existing project resources, enforces lifecycle order, validates terminal evidence, and cleans up fail-closed |
| Kubernetes-pods shim | Implemented, not rehearsed | `scripts/golden_soak/pods_shim.py` exposes exactly the initial JM/TM IDs through TLS and bearer auth; replacement, restart, wrong labels, bad health, and malformed Docker responses fail closed |
| CI workflow | Missing | No workflow dispatch, timeout, cancellation, artifact upload, or runner budget gate exists |
| Runtime proof | Host preflight only; live run blocked | The required Mac host has Docker and disk capacity, but its checkout lacks commit `45817b1` and the runtime/overlay files. Images, live TLS/socket behavior, health checks, traffic, exactness, and duration remain unproven |
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

The runtime controller adds the following fail-closed boundary without
changing the twelve-service overlay:

1. all eight manifest paths, byte sizes, and SHA-256 values are checked before
   the first Docker command;
2. existing containers, volumes, or networks carrying the requested Compose
   project label block build/up, so later `down -v` cannot adopt user data;
3. the shim and observer are transient `docker compose run` containers with
   explicit read-only pack/TLS mounts; the shim uses GET-only Docker socket
   inspection bound to the original JM/TM IDs;
4. baseline PASS precedes observer start, observer readiness precedes produce,
   and verifier PASS precedes final identity/restart checks;
5. bounded evidence, observer stop, transient-container removal, and
   project-scoped cleanup run on every post-start exit path; cleanup failure
   prevents PASS;
6. a count below `1440000` can emit only `REHEARSAL_PASS`. The full token is a
   capacity-independent result and still does not close the Mac rollback gate.

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

The foundation session used a RED-to-GREEN contract. Before the files existed,
all six foundation tests failed. After implementation and one narrow manifest
correction, its evidence was:

- `python -m pytest tests/unit/test_ci_soak_foundation.py -q` — `6 passed`;
- Ruff check and format check — passed;
- `py_compile` for the new unit contract — passed;
- merged Compose `config --quiet` — passed;
- byte size and SHA-256 checks for all eight pack files — passed;
- LF/NUL and known-secret-pattern scans for all 12 foundation files — passed;
- exact staged-path comparison and `git diff --cached --check` — passed.

The runtime session also used RED-to-GREEN. The initial focused contract had
`11 failed` because both modules were absent. The final implementation gate at
`45817b1` was:

- `python -m pytest tests/unit/test_ci_soak_runtime.py tests/unit/test_ci_soak_foundation.py -q` — `19 passed`;
- Ruff check and format check for the two modules and focused tests — passed;
- `py_compile` for both modules and the focused test — passed;
- merged Compose `config --quiet` — passed without starting containers;
- protected source-pack hashes — `8/8` matched;
- LF/NUL, trailing-whitespace, placeholder, and known-key-pattern scan — passed;
- exact five-path staged comparison and `git diff --cached --check` — passed.

The read-only rehearsal host preflight on 2026-08-19 established:

- the project rule routes Docker-heavy verification through SSH alias
  `deproject-mac`, so Windows Docker was not used;
- `/usr/local/bin/docker` is available on the Mac (`client 29.5.2`, daemon
  `29.2.1`) and the root filesystem reported 507 GiB available;
- the Mac checkout was at `ae9fb69` and did not contain commit `45817b1`,
  `scripts/golden_soak/runtime.py`, `scripts/golden_soak/pods_shim.py`, or
  `docker-compose.soak.yml`;
- the Mac checkout already had unrelated untracked paths, which must remain
  untouched;
- no build, container start, source transfer, checkout update, pull, or push
  was performed.

The live rehearsal therefore remains blocked until the user explicitly
authorizes a scoped delivery of the committed source snapshot to the Mac (or
an authorized push/fetch path). That authorization is an external mutation
boundary and is not implied by autonomy.

Revalidate the current configuration without starting services:

```powershell
python -m pytest tests/unit/test_ci_soak_foundation.py -q
python -m pytest tests/unit/test_ci_soak_runtime.py -q
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

Only the first item is the next named slice. Keep later items separate so a
green focused gate ends each turn.

1. **Authorize source delivery and run the short Mac rehearsal — next
   slice.** Explicitly authorize either a scoped committed-snapshot transfer
   into a new Mac directory or the required push/fetch path. Preserve the
   existing Mac checkout and its unrelated untracked files. After confirming
   the exact runtime source identity, use a fresh dedicated Compose project, a
   fresh output directory, and `--count 2000` to prove image build, readiness,
   live shim TLS/socket behavior, traffic, verifier compatibility, disk
   headroom, evidence, and cleanup. A rehearsal result must not be labelled a
   soak PASS. Do not raw-retry a failed build or rehearsal.
2. **Workflow wiring — later slice.** Add dispatch inputs, a hard timeout,
   `cancel-in-progress: false`, fail-closed finalization, and always-uploaded
   artifacts. This still does not authorize a push.
3. **Remote rehearsal and full run — external gates.** Require explicit push
   authorization, inspect current GitHub runner limits and free disk, dispatch
   the short rehearsal first, and attempt the full run only after its evidence
   is accepted.

## Next-session entry checklist

1. Check the latest user message for stop or process-frustration triggers.
2. Run `git status --short` and inspect the current `HEAD`; do not rely on an
   old ahead count in local notes.
3. Read this document, `scripts/golden_soak/README.md`, and the two focused
   contracts in `tests/unit/test_ci_soak_{foundation,runtime}.py`.
4. Preserve unrelated dirty and untracked files.
5. Do not modify the eight files under `scripts/golden_soak/pack/`.
6. Do not deliver files to or change the Mac checkout without explicit remote
   mutation authorization.
7. For a rehearsal, verify the Mac snapshot hashes first, then use a new
   Compose project name and empty output directory; keep workflow, full-soak,
   and Mac-gate claims outside that slice.

## Tracked file map

- `docker-compose.soak.yml` — foundation overlay.
- `scripts/golden_soak/MANIFEST.json` — pack provenance and integrity.
- `scripts/golden_soak/README.md` — fail-closed pack boundary.
- `scripts/golden_soak/runtime.py` — local lifecycle/evidence/cleanup controller.
- `scripts/golden_soak/pods_shim.py` — TLS PodList adapter bound to exact container IDs.
- `scripts/golden_soak/pack/` — immutable eight-file source reference.
- `tests/unit/test_ci_soak_foundation.py` — executable foundation contract.
- `tests/unit/test_ci_soak_runtime.py` — executable runtime/shim contract.
- `ci-soak-runtime-harness.md` — completed implementation checklist and scope boundary.
- `docs/operations/ci-soak-compose-foundation.md` — this canonical handoff.
