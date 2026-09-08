# Flink failure evidence retention

## Goal

Add a read-only watcher that preserves the first Flink failure window outside
the cluster before any future golden soak is allowed to start traffic.

## Tasks

- [x] Define RED tests for healthy arming, failure triggers, and the evidence bundle.
- [x] Implement the host-side watcher/collector under `scripts/`.
- [x] Document the pre-traffic launch and stop contract.
- [x] Run focused tests, lint/format checks, and a scoped diff review.

## Implementation record

**Last updated:** 2026-08-09

| Field | Current truth |
| --- | --- |
| Implementation commit | `195082f` — `feat(ops): retain Flink failure evidence` |
| Collector | `scripts/capture_flink_failure_evidence.py` |
| Contract tests | `tests/unit/test_flink_failure_evidence_capture.py` |
| TDD evidence | RED `3 failed, 1 passed` → GREEN `4 passed in 2.72s` |
| Static/CLI checks | Ruff lint PASS; Ruff format PASS; `watch --help` PASS |
| Runtime status | Not launched against kind/Colima; no live or SSH smoke performed |
| Product status | `candidate`; soak/rollback acceptance remains open |

The tests use a fake kubectl client and prove the command allowlist, bundle
shape, sanitization, fail-closed arming, log-capture priority, partial-bundle
reporting, and POSIX permission contract. They do not prove that the current
live stand exposes every configured selector, REST service, observer path, or
log surface. Validate those values in the separately authorized runtime slice.

## Pre-traffic contract

Run the watcher on the Kubernetes host, not in the cluster. Use a new directory
for each new soak identity on storage that survives pod, kind, and Colima
restarts. Do not use `/tmp`, a path inside this repository, or a directory from
a consumed soak identity.

Start the watcher before the producer with the real deployment values:

```text
python3 scripts/capture_flink_failure_evidence.py watch \
  --context <kubectl-context> \
  --namespace <namespace> \
  --flink-deployment <flinkdeployment-name> \
  --pod-selector '<jobmanager-and-taskmanager-selector>' \
  --flink-rest-service <rest-service-name> \
  --observer-job <observer-job-name> \
  --output-dir <host-persistent-directory> \
  --stop-file <unique-stop-file> \
  --expected-pods <jobmanager-plus-taskmanager-count>
```

Do not start traffic until `failure-watcher-state.json` contains both
`"state": "armed"` and `"armed": true`. Arming requires a `RUNNING` Flink job,
a `STABLE` FlinkDeployment lifecycle, a `READY` JobManager deployment, and the
exact expected number of Ready pods. It is an evidence-retention prerequisite,
not a replacement for the soak's task-readiness and checkpoint-growth gates.
If the watcher exits or times out before arming, do not start traffic.

For an observer whose chronology is already written to host storage, pass
`--observer-local-dir <directory>`. Otherwise the collector reads the three
observer evidence files from the observer pod's `/evidence` directory.

## Capture and stop contract

After the first post-arm failure signal, the watcher captures once and exits
with code `2`. It writes the triggering FlinkDeployment and sanitized pod
states first, captures the short-lived JM/TM current and previous logs before
secondary API surfaces, then retains namespace events, Flink REST history, and
observer chronology. `manifest.json` records partial-capture errors and is
`complete: false` when expected pods or requested evidence are unavailable.

If the run ends without a captured failure, create the unique `--stop-file`.
The watcher records `state: stopped` and exits `0`. Exit code `3` means its
configured timeout elapsed. Keep the output directory, watcher chronology,
state file, bundle, and manifest together. A manual `capture` command does not
arm the watcher and does not satisfy the pre-traffic contract.

The Kubernetes command surface is limited to `get`, `logs`, and
`exec ... -- cat`. The collector never applies, patches, deletes, restarts, or
executes a non-`cat` command. On POSIX hosts, directories are mode `0700` and
files are mode `0600`. Logs and exception history can still contain sensitive
runtime data: keep the output outside Git and do not paste it into tickets or
chat without review.

## Done When

- [x] A captured bundle contains JM/TM current and previous logs, Flink REST
      exception history, sanitized pod termination states, namespace events,
      and observer chronology.
- [x] The watcher issues read-only Kubernetes operations only and writes
      artifacts with private permissions on POSIX hosts.
- [x] Focused verification is green and the slice is committed locally.

## Next-session resume

Read in this order:

1. The top block of `AGENT_STATE.md`.
2. The top block of `docs/SESSION_HANDOFF.md`.
3. This document.
4. `docs/perf/golden-4h-soak-failures-01-05-rca-2026-08-09.md` only when
   working on the following Colima/runtime slice.

Then refresh `git status --short --branch` and `git log -3 --oneline`. Treat
the retention implementation as complete at `195082f`; do not reopen it
without new failing evidence or an explicit change request. Existing unrelated
untracked files are protected WIP and must remain untouched.

On this Windows checkout, the configured `.tmp/pytest-basetemp` currently has
an inherited ACL problem (`WinError 5`) from an older run. This is an
environmental setup failure, not a collector-test failure. Do not delete or
repair that directory automatically. For a focused recheck, use a fresh unique
base directory:

```powershell
$evidenceTestBase = ".tmp/pytest-failure-evidence-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
& '.\.venv\Scripts\python.exe' -m pytest `
  'tests\unit\test_flink_failure_evidence_capture.py' -q `
  --basetemp=$evidenceTestBase
```

No watcher or background writer is known to be active. The next separate
candidate is read-only diagnosis and stabilization planning for Colima guest
time, memory headroom, filesystem I/O, and containerd. Do not start traffic,
reuse soak identities `-01` through `-05`, mutate Kubernetes/Helm, elevate
production, or push without the required separate authorization.

## Notes

This slice does not start a soak, mutate Kubernetes or Helm, elevate production,
or authorize a push.
