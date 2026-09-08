# CI-soak r13-r16 runtime record (2026-08-22)

Owner-authorized Mac runtime session. All attempts ran on exact HEAD
`0988a0d3f6bd9c7f83a8eaefd2d779da2632e0d3` (the pushed audit_sol remediation
lineage) after a fresh local gate
`ARCHITECTURE_READY=PASS blockers=0 head=0988a0d3f6bd9c7f83a8eaefd2d779da2632e0d3`.
The `git archive` (9,938,888 bytes, SHA-256
`85256fb384b99e9a2901cd8768cca14d97c25228816abfefaaf955fa2cd13f49`) was
hash-verified on both hosts; extracted pack files matched `MANIFEST.json`
byte-for-byte. Attempt identities came from
`scripts/golden_soak/gen_attempt_bundle.py` (audit F-10); every expected hash
in every plan was computed programmatically, none hand-typed.

## Attempt ledger

### r13 — FAIL `up_core_failed` (bare controller, no wrapper)

`runtime.py --count 2000` without the guarded wrapper: compose MinIO could
not bind `0.0.0.0:9000` — the protected co-tenant MinIO holds that port.
Fail-closed cleanup completed (post-down containers/networks/volumes logs
empty). Lesson: the co-tenant stop/restore wrapper is a hard requirement
(ports, not only memory).

### r14 — FAIL `source_visibility_failed` (wrapper, root outside the mount)

Guarded wrapper with shared root `/Users/julia/ci-soak-0988a0d-r14-...`:
the Colima VM mounts ONLY `/Users/julia/agentflow-fc5-7113966` (rw
virtiofs), so any other root bind-mounts as an empty directory inside
containers. The source-visibility probe (SHA-256 of tracked
`verify_coschedule.py` through the daemon) failed closed at
`daemon_visibility_preflight`; stop was NOT invoked, co-tenants untouched,
lock released. A self-written output marker cannot catch this class — the
source probe must always hash a real tracked file. Fixed in commit
`770c089` (generator + runbook).

### r15 — PASS (guarded rehearsal)

Root under the virtiofs mount. Full guarded cycle: path policy PASS, both
visibility probes PASS (daemon-side hash `25d0ed66d0aa114801125af5b5d144ef
df42e271053325b85bf3eaf206b4d768` matched), ClickHouse health/host/workload
probes PASS, co-tenant stop `rc=0`, controller
`RESULT=REHEARSAL_PASS run=golden-4h-soak-rv-20260819-07 count=2000
gate=capacity-independent-rehearsal-only`, restore PASS with kind
identity/running/restart=0/apiserver=1/livez consecutive checks,
`lock_result=RELEASED`, `first_boundary=complete`. Post-restore manual
re-verify: CH healthy + both routes `1`, MinIO healthy, kind livez `ok`.
This closes the identity-bound preflight/rehearsal gate (audit F-02 item 1).

### r16 — FAIL `verify_failed` / `iceberg_exactness` (full 4h soak)

Same guarded cycle with `--count 1440000` @ 100 eps, verifier co-scheduled
before traffic. Wrapper: stop `rc=0`, controller invoked, restore PASS,
lock RELEASED — the fail is the controller verdict, not orchestration.

Producer final: `attempted=1440000 delivered=1440000 failures=0
delivered_eps=99.999486 elapsed_s=14400.07` (02:41:03Z-06:41:03Z).
Observer: 256/256 samples with Flink `RUNNING`, tasks 4/4,
`checkpoints_failed=0` (556+ completed at ~10 s cadence to the end),
`mem_available_kb` ~1.0M, disk ok. Verifier verdict:

```text
result=FAIL reason=iceberg_exactness physical=252332 unique=252332 invalid=0 missing=1187668 duplicates=0
```

Classification: a sustained lake-ingest throughput ceiling of ~17.5 eps on
the 4-CPU / 7 GiB Intel-iMac Colima VM — 252,332 of 1,440,000 events
reached Iceberg in the 4 h window plus grace. Zero duplicates and zero
invalid rows mean no correctness defect; producer, Kafka, and the Flink job
were healthy throughout. The full-soak gate therefore remains OPEN, now
with a measured capacity root cause instead of an unexplained failure.

## Resume boundary

r13-r16 identities, shared roots
(`/Users/julia/agentflow-fc5-7113966/ci-soak-0988a0d-r1{5,6}-20260822-01`),
and retained evidence are consumed — do not reuse, rerun, or clean. A later
full-soak attempt starts at r17+ with fresh identities from the generator
and must either run on a host whose lake path sustains 100 eps or follow an
explicitly re-scoped capacity contract decided by the owner. All four
protected co-tenants were verified running and healthy after each guarded
attempt.
