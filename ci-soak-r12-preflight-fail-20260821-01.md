# CI-soak r12 preflight failure — 2026-08-21

## Goal and authority

Execute one freshly authorized post-fix `--count 2000` rehearsal from exact
source HEAD `bfb82ecb6c66e5490db2d99bbdaf8b9da55f2082`, using new r12
snapshot/project/output identities and unconditional restoration of the four
exact protected co-tenants.

The rehearsal never reached a stop or controller invocation. The exact
classification is `PREFLIGHT_FAIL_BEFORE_STOP`.

## Local and read-only gates

The fresh local architecture gate passed:

```text
ARCHITECTURE_READY=PASS blockers=0 head=bfb82ecb6c66e5490db2d99bbdaf8b9da55f2082
```

The exact `git archive` was `17,981,440` bytes with SHA-256
`1654503d7a1cae3a95baf5f87e43a0411c93fb18db14250dd58a44a35a5252b7`.
Its local and remote hashes matched. The r12 preflight wrapper passed local and
native macOS `bash -n`; its SHA-256 was
`e3835c7a18d0ebba2464a0a08a413bf09d3b6428d85c2295f25201b3c427b946`.

Before any remote path was created, a strict read-only preflight passed. It
proved Docker API range `1.44..1.53`, four CPUs, `7,269,556,224` bytes of
memory, no r12 snapshot/control/output/preflight/owner-lock identity, project
resources `0/0/0`, no r12 probes or controller, and the expected Mac checkout
HEAD/status. All four protected exact IDs were running with restart count zero;
MinIO, Iceberg, both ClickHouse routes, Kind `/livez`, and the one-apiserver
check passed. The retained rollback ClickHouse remained exited cleanly and
disconnected.

The preceding r11 authorization was consumed by read-only orchestration only.
Its first probe exposed an unsupported Docker template and its corrected probe
then stopped on the expected no-match exit from `pgrep` under `pipefail`. No
r11 remote identity, lock, project resource, probe, stop, or controller was
created. The r12 probe carried the bounded `pgrep || true` correction and
passed completely.

## Terminal r12 preflight failure

The preflight wrapper was invoked exactly once. It extracted the exact source,
verified the protected source hashes including `verify_coschedule.py`, captured
the source visibility hash, and then failed before the output visibility
container or Compose validation:

```text
PREFLIGHT_RESULT=FAIL
REASON=output_marker_hash_mismatch
ATTEMPT_ID=ci-soak-bfb82ec-r12-preflight
PROJECT_RESOURCES=0/0/0
OWNER_LOCK_RELEASE=PASS
STOP_COMMAND=NOT_INVOKED
CONTROLLER=NOT_INVOKED
```

The terminal preflight result SHA-256 is
`9a47518e73a724f7f105beaa79e7c7ad794da3d633694d2e2cb69e6fb7c59bb1`.
The wrapper contained output marker text `ci-soak-output-bfb82ec-r12` but
retained the r11 marker hash
`a451640563c229772e9d8fa5287f6a20bace28a11f1b62b8086017b6a35b62a8`.
The correct SHA-256 for the r12 text is
`9853a9344b1378f968eb4f5c808c6541275746d6f5682a507b6d3294d4bfb6f2`.
No correction or rerun used the consumed r12 identities.

## Independent safety postflight

The independent read-only postflight exited `0` and proved:

- the owner lock and r12 controller were absent;
- r12 project resources were `0/0/0` and all four r12 probe counts were zero;
- the four protected exact IDs were still running with restart count zero;
- MinIO/Iceberg, host and workload ClickHouse routes, Kind `/livez`, and the
  one-apiserver check passed;
- the rollback ClickHouse and original Mac checkout were unchanged;
- the r12 snapshot, control directory, empty output identity, and preflight
  evidence remain retained.

No co-tenant stop, controller, traffic, full soak, rollback exercise,
production action, cleanup of retained evidence, fetch, or push occurred.
Grok was not used.

## Resume boundary

Treat the r11 and r12 local control identities and all r12 remote paths as
consumed evidence. Do not rerun, overwrite, adopt, or clean them. A later
attempt starts at r13 or later with a fresh exact-HEAD gate, new archive,
snapshot/project/output/control/attempt identities, a corrected marker hash,
fresh read-only preflight, and fresh explicit authorization.
