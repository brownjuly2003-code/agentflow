# CI soak Compose foundation and runtime harness: current state and handoff

**Last updated:** 2026-08-19

**Status:** soak-only 90-second Flink JobManager startup grace implemented and
verified in one isolated Mac health check; cleanup independently confirmed;
no rehearsal PASS

**Foundation commit:** `9dffe47` (`feat(ops): add CI soak Compose foundation`)

**Runtime contract commit:** `45817b1` (`feat(ops): add fail-closed CI soak runtime harness`)

**Startup-grace commit:** `cfd7b1c` (`fix(ops): give soak JobManager startup grace`)

## Read this first

- The repository contains a tracked source pack, a Docker Compose topology, a
  local runtime controller, and an identity-bound Kubernetes-pods shim.
- It does not contain a CI workflow. None of the three controller attempts
  reached baseline, shim, traffic, or verification. A later health-only run
  verified the corrected JobManager readiness boundary without running the
  controller; no rehearsal PASS exists.
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
| Compose topology | Tracked, configuration-validated | `docker-compose.soak.yml`, merged with the base and Flink Compose files; the overlay adds only a 90-second JobManager `start_period` |
| Foundation contract | Green at commit time | `tests/unit/test_ci_soak_foundation.py`: 7 tests passed |
| Runtime harness | Implemented; exercised through `up-core` | `scripts/golden_soak/runtime.py` validated the complete pack, rejected no pre-existing resources, built both local images on the second attempt, published FAIL evidence, and cleaned the named Compose projects |
| Kubernetes-pods shim | Implemented, not rehearsed | `scripts/golden_soak/pods_shim.py` exposes exactly the initial JM/TM IDs through TLS and bearer auth; replacement, restart, wrong labels, bad health, and malformed Docker responses fail closed |
| CI workflow | Missing | No workflow dispatch, timeout, cancellation, artifact upload, or runner budget gate exists |
| Runtime proof | JobManager health correction verified; rehearsal still open | The pre-fix controller attempts failed before baseline. A focused post-fix Mac run observed only `starting` then `healthy`, REST HTTP 200 at 67 seconds, Docker healthy at 73 seconds, zero restarts/OOM, and a green 20-second hold. Shim TLS/socket behavior, traffic, exactness, and duration remain unproven |
| Push or remote mutation | Scoped snapshot transfer and isolated health lifecycle only | Commit `45817b1` was archived into a new Mac directory, and a later fresh Compose project verified the committed `cfd7b1c` overlay. No push, pull, fetch, checkout change, image change, or mutation of the existing Mac worktree occurred |

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

The focused JobManager diagnosis then isolated the readiness failure:

- a fresh project `agentflow-ci-soak-flinkdiag-01` started the same four core
  services from the cached image
  `sha256:205d6fc0427e70eb2890e8fa235e62011b6a3b79c8c08814750476228485dab3`
  without rebuilding or running the soak controller;
- the current JobManager healthcheck is `curl -f /overview`, interval 10s,
  timeout 5s, five retries, and no `start_period`;
- the JobManager remained running with zero restarts and no OOM while checks
  failed with `curl` exit 7 because port 8081 was not listening;
- host REST first returned HTTP 200 at the 53-second sample and Docker health
  became `healthy` at 66 seconds. The JVM used about 267 MiB of its 1.758 GiB
  limit and the Flink REST endpoint returned version `2.3.0` normally;
- the full log shows ordinary actor-system, dispatcher, and REST initialization
  with no terminal JVM exception. The earlier `jdk.compiler` warnings are not
  the readiness cause;
- therefore the failure is at the Compose orchestration boundary: the
  zero-grace five-failure budget is narrower than observed variable startup,
  and the full build/core path can mark a live JobManager unhealthy before its
  REST endpoint opens;
- `/opt/flink/log` was copied to
  `.artifacts/flink-jobmanager-diag-01/flink-log` before cleanup. The diagnostic
  trap removed its four containers, four volumes, and network, and final label
  checks were empty.

### Cleanup evidence closure

The diagnostic script itself emitted `DIAG_CLEANUP=PASS` after its scoped
cleanup, and its immediate project-label checks were empty. The later
`REMOTE_PROJECT_*=0` markers remain invalid because their shell could not find
Docker, but the independent evidence gap is now closed.

On 2026-08-19, one bounded read-only recheck used the explicit verified
`/usr/local/bin/docker` executable and queried only Compose project
`agentflow-ci-soak-flinkdiag-01`. Container, volume, and network label queries
each exited `0` and returned zero identities. No remote resource was created,
changed, or removed. Do not repeat this cleanup query without new evidence.

### Local startup-grace correction

- Commit `cfd7b1c` adds only `healthcheck.start_period: 90s` under the soak
  overlay's `flink-jobmanager`; the base healthcheck remains unchanged.
- Grok ran through `local_grok_cli`, requested model `grok-4.6`, actual model
  `grok-4.6-build`, RunId
  `de-ci-soak-jm-start-period-20260819-grok01`. Its RED run was
  `1 failed, 6 passed` with the expected missing-`healthcheck` `KeyError`; its
  GREEN run was `7 passed`.
- The independent gate passed `20` foundation/runtime tests, Ruff check and
  format, `py_compile`, `git diff --check`, LF/NUL checks, and all eight
  protected pack hashes. Merged Compose JSON preserved the base curl test,
  10-second interval, 5-second timeout, and five retries while normalizing the
  new start period to `1m30s`.
- That local correction slice started no container or image build. The later
  focused health check below is a separate runtime slice.

### Focused post-fix Mac health check

- The latest user authorization covered one fresh project,
  `agentflow-ci-soak-health-cfd7b1c-01`, and deletion only of resources created
  by that project. The run used evidence root
  `/Users/julia/agentflow-ci-soak-health-cfd7b1c-20260819-01` and did not run
  the soak controller.
- The exact committed overlay SHA-256 was
  `a172b5178d85a4c6e836a5dc083fe7a5b7637567ef564652b5e4d1aea89cae9a`.
  Base and Flink Compose hashes matched the immutable `45817b1` snapshot, and
  `--no-build --pull never` pinned cached Flink image
  `sha256:205d6fc0427e70eb2890e8fa235e62011b6a3b79c8c08814750476228485dab3`.
- The JobManager timeline contained 15 samples over 73 seconds and only the
  states `starting` then `healthy`; it contained no `unhealthy`, restart, or
  OOM sample. REST first returned HTTP 200 at 67 seconds and Docker became
  healthy at 73 seconds. Inspect recorded the exact curl probe, `start_period`
  90 seconds, interval 10 seconds, timeout 5 seconds, five retries, restart
  count zero, and OOM false.
- After a further 20-second hold, the same container identity remained healthy
  and Flink 2.3.0 returned `/overview`. Kafka, MinIO, ClickHouse, and the
  JobManager were all healthy before cleanup.
- The bounded log scan found no OOM, exception, fatal line, or uppercase
  `ERROR` level. Its sole case-insensitive `error` match was an INFO message
  that the optional Hadoop FS provider was not packaged.
- `result-final.txt` emitted
  `RESULT=HEALTH_PASS reason=startup_grace_verified cleanup=PASS`. Its SHA-256
  is `b78dda2ad1806342380d208d090da34ff08801abfd3b4c8f779aae46a6604745`;
  timeline SHA-256 is
  `2f2284953131ab6c8233d1d62a0d42ba646aff568c9bd72f8bc5b8ed7a1817b8`,
  and inspect SHA-256 is
  `10eaa2d3f1b41f8cabb1019ece6b41f7df4cfac6259fbbb819e8934c2a2b36e9`.
- Scoped `compose down -v` removed four containers, four volumes, and the
  project network. Fresh independent label queries returned zero containers,
  volumes, and networks. The existing Mac checkout, source snapshot, cached
  images, and unrelated Docker resources remained untouched.
- This is a health-boundary PASS only. It is not `REHEARSAL_PASS`, traffic,
  exactness, shim, duration, CI workflow, or Mac rollback evidence.

### Recorded authorization boundary

The latest authorization was consumed by the single focused health lifecycle
described above. It did not authorize another rehearsal, workflow, push, image
deletion, existing-checkout mutation, or unrelated Docker cleanup. A future
session must still check the latest user message before creating or deleting
remote resources; the existing Mac checkout, unrelated Docker resources, and
image cache remain out of scope.

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

1. **Short Mac rehearsal — next external slice.** Only after a new explicit
   authorization, use a new Compose project and output directory with
   `--count 2000`. It may emit only `REHEARSAL_PASS`; do not describe it as a
   four-hour soak PASS or reuse the completed health project.
2. **Workflow wiring — later slice.** Add dispatch inputs, a hard timeout,
   `cancel-in-progress: false`, fail-closed finalization, and always-uploaded
   artifacts. This still does not authorize a push.
3. **Remote full run — external gate.** Require explicit push
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
6. Preserve the isolated Mac snapshot and all three rehearsal FAIL evidence
   directories; do not change the existing Mac checkout.
7. Treat the old `REMOTE_PROJECT_*=0` output as invalid. The corrected explicit
   Docker-path recheck is complete and found zero resources; do not repeat it
   without new evidence.
8. Preserve the completed health evidence root and do not repeat its project or
   lifecycle without new evidence.
9. The next remote action, only if explicitly authorized, is one short
   `--count 2000` rehearsal with a different new Compose project and empty
   output directory. Keep workflow, full-soak, and Mac-gate claims outside
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
