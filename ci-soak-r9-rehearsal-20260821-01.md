# CI-soak r9 rehearsal — 2026-08-21

## Goal

Execute exactly one authorized `--count 2000` rehearsal from the verified r9
snapshot, while temporarily stopping and then restoring the four protected
co-tenants by exact container ID.

## Fixed identities

- Source/gate HEAD: `7e8ec87c25bbdc8f8aa58c116ded9914470789cb`
- Snapshot: `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-7e8ec87-r9`
- Compose project: `agentflow-ci-soak-7e8ec87-r9`
- Output: `.artifacts/soak-rehearsal-2000-7e8ec87-r9` under the snapshot
- Attempt: `ci-soak-7e8ec87-r9-rehearsal-20260821-01`

## Tasks

- [x] Recover the exact r9 identities and confirm a clean tracked baseline.
- [x] Validate hash-pinned control artifacts locally and on the Mac.
- [x] Run one guarded controller invocation with `--count 2000`.
- [x] Independently verify terminal evidence, zero candidate residue, and
      exact-ID restoration of all four co-tenants.
- [x] Record the outcome in durable handoff documentation and create one
      explicit-pathspec local commit when the evidence is scoped and valid.

## Exclusions

No second controller attempt without a narrowed diagnostic correction. No
full soak, rollback execution, cleanup of retained evidence, production
action, fetch, or push.

## Done when

- [x] A fail-closed wrapper terminal record exists for the single attempt.
- [x] The reserved project has zero containers, networks, and volumes; no
      candidate writer or owner lock remains.
- [x] MinIO, Iceberg REST, dual-route ClickHouse, and Kind are restored under
      their exact recorded IDs with restart count zero.

## Outcome

The single controller invocation failed closed:

```text
RESULT=FAIL reason=verify_failed
verify: result=FAIL reason=catchup_rate_floor
ch_pipeline_phys=291 ch_pipeline_uniq=291
ch_orders_phys=291 ch_orders_uniq=291 expected=2000
```

The producer itself passed with `2000/2000` delivered, zero failures, and
`21.182s` elapsed (`94.418541` delivered eps). Under `dual_mean_90`, the
deadline was producer start plus `2000/90 = 22.222s`, leaving only `1.040s`
after the observed producer end. The verifier log was not created until about
`4.2s` after that deadline because the controller launches verification in a
new Compose one-off container. Therefore the short rehearsal could not observe
or prove the required applied mean with the current sequential orchestration;
the first query also showed that only `291/2000` rows had reached both
ClickHouse surfaces.

Wrapper SHA-256 evidence:

- `wrapper-result.json`:
  `91d7345c75f5d145570c9c4e5c5e716a6c5dc26d8a5859738fdf3964fbb3acef`
- `result-final.txt`:
  `d1083df031a21f392f08e56ed29bbba03078fe1c31e3c5d8767de0ba31524564`
- `runtime-state.json`:
  `b73ca3b81a529d4fffb615068a025c81b81e9827fab88570235cc5bd8cd7da17`
- `verify.log`:
  `f03732ea857bf52ff568ea549af9ec636ce5de818db9c4fbe2b0700378928503`

The wrapper reported `stop_rc=0`, `controller_invocation=INVOKED`,
`restore_rc=0`, `restore_result=PASS`, and `lock_result=RELEASED`. Independent
postflight found candidate resources `0/0/0`, no owner lock or writer, the four
protected exact IDs running with restart count `0`, and the retained rollback
ClickHouse exited cleanly and disconnected. The Mac checkout was unchanged.

## Next boundary

The r9 snapshot/project/output identity is consumed failure evidence and must
not be reused. Do not rerun this controller. A correction needs a separate
local TDD slice that makes the short-run rate observation compatible with the
strict dual-mean deadline without weakening the `90 eps` contract. Any later
external attempt requires a new exact-HEAD gate, fresh snapshot/project/output
identities, a fresh preflight, and new authorization. Full soak, rollback,
cleanup, production work, and push remain unauthorized.
