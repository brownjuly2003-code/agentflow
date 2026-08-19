# CI soak Compose foundation and runtime harness: current state and handoff

**Last updated:** 2026-08-19

**Status:** user-directed third Mac rehearsal completed; no PASS; the Flink
JobManager health boundary reproduced

**Foundation commit:** `9dffe47` (`feat(ops): add CI soak Compose foundation`)

**Runtime contract commit:** `45817b1` (`feat(ops): add fail-closed CI soak runtime harness`)

## Read this first

- The repository contains a tracked source pack, a Docker Compose topology, a
  local runtime controller, and an identity-bound Kubernetes-pods shim.
- It does not contain a CI workflow. The controller has now been run against
  live containers, but none of the three attempts reached baseline, shim, traffic, or
  verification, and no rehearsal PASS exists.
- No container was built or started while either implementation slice was
  developed and verified; the later rehearsal described below was a separate
  runtime slice.
- An authorized byte-verified snapshot was copied to a new Mac directory. The
  existing Mac checkout and its unrelated untracked files were not changed.
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
| Runtime harness | Implemented; exercised through `up-core` | `scripts/golden_soak/runtime.py` validated the complete pack, rejected no pre-existing resources, built both local images on the second attempt, published FAIL evidence, and cleaned the named Compose projects |
| Kubernetes-pods shim | Implemented, not rehearsed | `scripts/golden_soak/pods_shim.py` exposes exactly the initial JM/TM IDs through TLS and bearer auth; replacement, restart, wrong labels, bad health, and malformed Docker responses fail closed |
| CI workflow | Missing | No workflow dispatch, timeout, cancellation, artifact upload, or runner budget gate exists |
| Runtime proof | FAIL before baseline | Attempt 1 failed resolving the pinned Flink base through Docker DNS. After registry recovery, attempts 2 and 3 built both images but `flink-jobmanager` became unhealthy during `up-core`. Shim TLS/socket behavior, traffic, exactness, and duration remain unproven |
| Push or remote mutation | Scoped snapshot transfer only | Commit `45817b1` was archived into a new Mac directory after explicit authorization. No push, pull, fetch, checkout change, or mutation of the existing Mac worktree occurred |

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

The authorized live rehearsal then produced this evidence:

- local `git archive` SHA-256
  `369ac0e176b8c5479d1b1117b5c8b231ab76255fe44200ffda947c4b0f20ae86`
  matched after transfer, and the remote Git blob IDs for `runtime.py`,
  `pods_shim.py`, and `docker-compose.soak.yml` matched commit `45817b1`;
- the snapshot was extracted only under
  `/Users/julia/agentflow-ci-soak-rehearsal-45817b1-20260819-01`; the existing
  checkout at `ae9fb69` remained untouched;
- attempt 1 (`agentflow-ci-soak-45817b1-r1`) emitted
  `RESULT=FAIL reason=build_flink_failed` when BuildKit DNS returned
  `no such host` for `registry-1.docker.io`; cleanup completed and the final
  project-label counts were zero containers, zero volumes, and zero networks;
- host DNS and HTTPS subsequently resolved the registry, and Buildx read the
  exact pinned Flink digest. This new evidence permitted the one bounded retry;
- attempt 2 (`agentflow-ci-soak-45817b1-r2`) built both `flink-job-runner` and
  `agentflow-api`, then emitted `RESULT=FAIL reason=up_core_failed` because
  `flink-jobmanager` became unhealthy. Its captured container log contains the
  standalone-session start plus repeated `Unknown module: jdk.compiler`
  warnings, but no decisive healthcheck failure detail;
- attempt 2 never reached the shim, baseline, observer, producer, or verifier.
  `compose-down` returned zero after removing four containers, four named
  volumes, and the project network; a fresh label query returned no project
  containers, volumes, or networks;
- on the next user turn, the user explicitly requested attempt 3 despite the
  recorded no-raw-retry recommendation. Its fresh output and project IDs were
  `soak-rehearsal-2000-r3` and `agentflow-ci-soak-45817b1-r3`; snapshot SHA-256
  and empty-resource preflights passed;
- attempt 3 used the cached successful image builds and reproduced
  `RESULT=FAIL reason=up_core_failed`. MinIO and ClickHouse became healthy,
  Kafka was still starting, and the JobManager was running but unhealthy after
  about one minute. Its fuller log reached `Trying to start actor system` and
  continued cluster initialization, with no terminal JVM exception captured.
  This supports, but does not prove, a startup/readiness-budget cause;
- attempt 3 also stopped before shim or baseline. `compose-down` returned zero
  and final label queries again found no project containers, volumes, or
  networks;
- pulled and locally built image cache remains on the Mac. It is outside
  Compose `down -v`, can be shared, and was not destructively removed without
  a pre-run ownership baseline.

Evidence remains in `.artifacts/soak-rehearsal-2000` and
`.artifacts/soak-rehearsal-2000-r2` and
`.artifacts/soak-rehearsal-2000-r3` under the isolated snapshot directory.
There is no PASS token and no traffic result.

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

1. **Flink JobManager readiness diagnosis — next slice.** Do not launch a
   fourth raw rehearsal. Use the existing isolated snapshot and built image for
   one focused diagnostic that preserves `docker inspect .State.Health` and
   the complete JobManager logs before cleanup. Establish whether the failure
   is the healthcheck command, startup budget, JVM/module state, or another
   concrete cause before changing code or Compose. Any behavioral correction
   must start with a failing focused test.
2. **Short Mac rehearsal after a verified correction — later slice.** Use a
   new Compose project and output directory with `--count 2000`. It may emit
   only `REHEARSAL_PASS`; do not describe it as a four-hour soak PASS.
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
3. Read this document, `scripts/golden_soak/README.md`, and the two focused
   contracts in `tests/unit/test_ci_soak_{foundation,runtime}.py`.
4. Preserve unrelated dirty and untracked files.
5. Do not modify the eight files under `scripts/golden_soak/pack/`.
6. Preserve the isolated Mac snapshot and both FAIL evidence directories; do
   not change the existing Mac checkout.
7. Do not run a fourth raw rehearsal. Diagnose the JobManager health boundary
   in a distinct focused slice first.
8. After a verified correction, use a new Compose project name and empty
   output directory; keep workflow, full-soak, and Mac-gate claims outside
   that slice.

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
