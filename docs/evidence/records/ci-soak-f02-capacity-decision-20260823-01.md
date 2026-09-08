# CI-soak F-02 capacity decision (2026-08-23)

**Decision ID:** `CI_SOAK_F02_CAPACITY_DECISION_20260823_01`.
**Authority:** session-delegated owner decision (owner instruction
2026-08-23: continue autonomously, decisions delegated). The owner may
override this record before any r17+ attempt.

## Inputs

- r16 terminal verdict (`ci-soak-r13-r16-runtime-20260822-01.md`):
  producer 1,440,000/1,440,000 @ 99.999 eps, Flink RUNNING with 0 failed
  checkpoints for the full 4 h, verifier
  `FAIL reason=iceberg_exactness physical=252332 ... missing=1187668
  duplicates=0 invalid=0` — a measured sustained lake-ingest ceiling of
  ~17.5 eps on the 4-CPU / 7 GiB Intel-iMac Colima VM. No correctness
  defect was observed.
- Root plan (`golden-4h-soak-rollback-gate.md`) requires 4 h @ 100
  delivered eps with exact lake+serving counts, explicitly "without
  weakening criteria".
- The runtime harness pins the rate contract: `runtime.py` raises
  `rate_contract_invalid` for any `--rate-eps` other than the required
  100. A reduced-rate attempt therefore requires a tracked contract
  change, not a flag.
- The serving-path 4 h @ 100 eps gate was already closed on r4
  (2026-07-19, `docs/perf/throughput-realpath-paced100-4h-r4-2026-07-19.md`);
  the open F-02 item is the golden-topology soak whose missing half is
  lake-path (Iceberg) capacity.

## Options considered

1. **r17 at a reduced rate on the current host** — rejected. It requires
   weakening the pinned rate contract, contradicts the root plan's
   "without weakening criteria" bound, cannot close the gate as written,
   and burns a non-reusable attempt identity for side evidence only.
2. **Re-scope the capacity contract to the measured ceiling** — rejected
   for the same bound. The correctness properties the reduced-rate run
   would demonstrate (0 dup / 0 invalid over 4 h) are already on record
   from r16.
3. **Run r17+ on a host whose lake path sustains 100 eps** — accepted as
   the only closing path. No such host is currently available: the
   Windows workstation is unsuitable for the runtime stand, and the
   iMac VM ceiling is measured.

## Decision

- The golden full-soak gate (audit F-02 runtime half) **remains OPEN**,
  classified `BLOCKED_HOST_CAPACITY` with a measured root cause.
- No r17+ attempt is authorized on the current iMac VM; no harness or
  contract change is made; consumed identities r9–r16 stay consumed.
- Unblock condition: a host whose lake path demonstrably sustains
  ≥100 eps. Before burning an r17 identity there, run the root plan's
  bounded canary (task 4) on that host first.
- This record supersedes "decide with the owner before burning
  identities" in `_NEXT_SESSION.md` for the *negative* direction only:
  not attempting r17 on the current host needs no further sign-off; any
  future r17+ attempt still requires the fresh-identity and canary
  gates above.
