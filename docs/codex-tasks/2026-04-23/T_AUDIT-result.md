# T_AUDIT — Full project audit result (2026-04-23)

**HEAD audited:** `a010a2d95001ad7105454eb60fd252bd296a3c7d`
**Audit completed:** `2026-04-23 09:21 +03:00`
**Audited by:** Codex (`TA01..TA10`)

## TL;DR

- Code quality: `yellow` - T00 hardening itself is clean (`TA03`), but repo health is still gated by workflow contracts, docs drift, and unresolved test/bootstrap issues (`TA02`, `TA04`, `TA06`).
- CI: `4/15 workflows green` - `6/15` workflows are red and `5/15` still have no fresh `main` proof (`TA01`).
- Tests: `602 passed / 8 failed / 1 skipped` across `611` checks - failures are concentrated in runnable-script bootstrap, one chaos timeout path, and missing `schemathesis` in the documented install (`TA02`).
- Security: `yellow` - Trivy has `0` actionable HIGH/CRITICAL findings, but Safety is currently a false-green control because it scans version ranges instead of resolved versions (`TA07`).
- Architectural debt: `6 items` - the highest-leverage near-term items are query mixin contracts, Helm values validation, and Python extras contract rationalization (`TA08`).
- **Go/no-go for next sprint:** `GO` for an internal stabilization sprint; `NO-GO` for a customer-facing release until `T10`, `T11`, `T12`, and `T14` are closed and fresh `main` runs prove `CI`, `E2E`, `Staging`, and `Security` on the final HEAD.

## Sprint CI repair retrospective (2026-04-22 -> 2026-04-23)

**Closed:** `T00`, `T01`, `T02`, `T03`, `T04`, `T05`, `T_AUDIT`

**Outcome:** The sprint removed the import-level `pyiceberg` blocker, confirmed that `T00` hardening did not introduce runtime regressions, and converted the remaining red state into a bounded follow-up backlog. The repo is no longer in an "unknown red" condition: current failures are specific workflow, environment, performance, and process-contract issues with named owners-to-be and scoped tickets.

**Mistakes:**
1. `ecc137c` fixed several workflow install lines but missed `ci.yml:test-integration`, so CI repair was declared before the full extras surface was re-audited (`TA01`, `TA04`).
2. The team treated "job no longer dies on import" as "job repaired"; once collection advanced, the real failures appeared in coverage enforcement and `/warehouse` filesystem permissions (`TA01`, `TA02`).
3. The GitHub E2E workflow coupled success to a brittle compose-health parser, so healthy services still timed out before pytest started (`TA01`, `TA02`).
4. The Security workflow trusted a Safety signal that was generated from dependency ranges, not resolved installed versions, leaving a false-green process gap (`TA07`).

**Wins:**
1. The only allowed quick fix was already on `main` as `bbde79c`, and `test-integration` now reaches real execution instead of failing on `ModuleNotFoundError: pyiceberg` during collection (`TA01`).
2. `TA03` reviewed all 9 runtime-relevant `T00` hardening checkpoints and found no regressions, which sharply narrowed the search space for remaining incidents.
3. Local `tests/e2e/` passed `17/17`, proving that the current app stack can run end-to-end and isolating the GitHub E2E red state to workflow orchestration rather than a broad product defect (`TA01`, `TA02`).
4. The audit produced an explicit backlog: `12` operational follow-up tickets in `2026-04-24/` and `6` Q2 architectural debt tickets from `TA08`.

## Per-section findings

### TA01 CI matrix

| Signal | Summary |
|--------|---------|
| Workflow state | `4/15` green: `Nightly Backup`, `Contract Tests`, `DORA Metrics`, `Security Scan`. `6/15` red and `5/15` have no fresh `main` proof. |
| Main blockers | `CI` fails on coverage (`62.27% < 80%`) and `/warehouse` permission in one integration test; `E2E Tests` fail before pytest due to compose-health parsing; `Load Test` fails on real latency thresholds; `Staging Deploy` fails on webhook callback delivery. |
| Interim red with bounded explanation | `Chaos Engineering` and `Nightly Performance` were last red on pre-fix SHAs and now need fresh scheduled/main proof before another code change is justified. |
| Follow-up set | `T10`, `T11`, `T12`; existing `T06`, `T07`, `T08`, `T09`. |

### TA02 Test catalog

| Signal | Summary |
|--------|---------|
| Local suite status | `611` checks: `602 passed`, `8 failed`, `1 skipped`. |
| Failure concentration | `6` unit failures and `1` integration failure all reduce to the same root cause: direct execution of `scripts/*.py` without bootstrapping the repo root into `sys.path` (`T17`). |
| Remaining failures | The only non-bootstrap test failure is the chaos timeout path that returns `500` instead of `replay_pending` (`T18`). The only skip is the contract suite path that lacks `schemathesis` in the documented install (`T19`). |
| Cross-source synthesis | Local `tests/e2e/` are fully green, so the red GitHub E2E workflow from `TA01` is a workflow/orchestration problem, not evidence of a broad runtime regression. |

### TA03 T00 hardening review

| Signal | Summary |
|--------|---------|
| Functional verdict | `9/9` runtime-relevant hardening checkpoints were reviewed and all are `ok`; no regression tickets were opened. |
| Main implication | Current red workflows should be traced to CI contracts, dependency installs, and environment assumptions, not to the `T00` hardening commit itself. |

### TA04 Extras matrix

| Signal | Summary |
|--------|---------|
| Closed gap | `ci.yml:test-integration` is already on `.[dev,cloud]`; the old `pyiceberg` collection blocker is closed. |
| Active dependency gaps | `CI/perf-check` still misses `,cloud` (`T06`), and `mutation.yml` installs unused `integrations` where `cloud` is the real requirement (`T07`, `A06`). |
| Over-install | `CI/test-unit` can drop root `,integrations` because `./integrations[mcp]` already supplies the only integration dependencies those tests use. |

### TA05 Stale code

| Signal | Summary |
|--------|---------|
| Dead code / tracked artifacts | No actionable unused modules, orphan tests, tracked runtime artifacts, stale branches, or stale tags were found. |
| Hygiene issue | `.gitignore` currently hides local DuckDB/Iceberg runtime state via an over-broad `AgentFlow*` wildcard instead of explicit runtime rules (`T13`). |

### TA06 Docs alignment

| Signal | Summary |
|--------|---------|
| Drift scope | `README.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/runbook.md`, `docs/helm-deployment.md`, and contributor docs are out of sync with the post-repair repo state. |
| Highest-risk mismatches | Setup docs under-specify the full extras install, top-level status text is stale, and docs still describe `docker-compose.prod.yml` as the E2E path where workflows now use `docker-compose.e2e.yml`. |
| Recommended fix | One doc-alignment PR should update contributor install guidance, release/status wording, E2E compose references, and audit trail links in one pass. |

### TA07 Security

| Signal | Summary |
|--------|---------|
| Trivy | `6` HIGH, `0` CRITICAL, `0` actionable; all current HIGH findings are unfixed Debian base-image issues, so `ignore-unfixed: true` is behaving as configured. |
| Safety | The current job is a false green because it scans dependency specifier ranges rather than resolved installed versions (`T14`). |
| Bandit | No new findings versus baseline; the only remaining issue is the pre-existing `B310` baseline in `src/serving/backends/clickhouse_backend.py`. |

### TA08 Architectural debt

| Priority band | Item | Why it matters now |
|---------------|------|--------------------|
| Next sprint | `A02` Query engine mixin host contracts | The query layer still relies on hidden host attributes, and the broad `attr-defined` suppression leaves future refactors vulnerable to runtime-only breakage. |
| Next sprint | `A05` Helm values contract validation | Staging already failed once on an implicit API-key schema change (`key_id`), so schema validation is the shortest path to preventing repeat rollout failures. |
| After CI stabilization | `A06` Python extras contract rationalization | The repeated `cloud`/`integrations` mismatches across workflows show that dependency profiles are still managed ad hoc. |

Deferred but still real: `A01` SDK package-name collision, `A03` entity latency re-baselining, `A04` CDC strategy decision.

### TA09 Memory sync

| Signal | Summary |
|--------|---------|
| State sync | `.workflow/logs/errors.jsonl` and Claude memory were updated during `TA09` to the `a010a2d` baseline and the then-known blockers. |
| TA10 extension | Final TA10 consolidation extends that backlog to the full operational set `T06..T14`, `T17..T19` and records the final release verdict below. |

## Open follow-up tickets (after TA01..TA09)

| Ticket | Priority | Estimate | Owner |
|--------|----------|----------|-------|
| `T06` | `P1` | `3-5ч` | `TBD` |
| `T07` | `P2` | `2-4ч` | `TBD` |
| `T08` | `P2` | `2-3ч` | `TBD` |
| `T09` | `P1` | `2-4ч` | `TBD` |
| `T10` | `P0` | `2-4ч` | `TBD` |
| `T11` | `P1` | `1-2ч` | `TBD` |
| `T12` | `P1` | `1-3ч` | `TBD` |
| `T13` | `P2` | `1-2ч` | `TBD` |
| `T14` | `P1` | `1-2ч` | `TBD` |
| `T17` | `P1` | `1-2ч` | `TBD` |
| `T18` | `P1` | `1-2ч` | `TBD` |
| `T19` | `P2` | `30-60м` | `TBD` |

## Recommendation

### For next sprint (immediate, this week)

1. Close the release-blocking workflow truth gaps: `T10`, `T11`, `T12`, `T14`. Exit condition: fresh `main` proof for `CI`, `E2E Tests`, `Staging Deploy`, and a Security workflow that scans resolved versions.
2. Remove the remaining Python execution-contract drift: `T06`, `T17`, `T18`, `T19`. Exit condition: no workflow or local documented path relies on implicit extras or implicit `PYTHONPATH`.
3. Keep `T07`, `T08`, `T09`, `T13` in the same backlog but behind the release-blocking set; they matter, but they do not prevent this week's stabilization verdict.

### For Q2 2026 (architectural)

1. Start with `A05` and `A06` to formalize deployment/input contracts and dependency profiles; both are directly causing repeated CI/staging churn.
2. Take `A02` next so the semantic-layer/query work stops relying on hidden host attributes and broad mypy suppression.

### Defer

1. Defer `A01` until packaging/release coordination is scheduled, because the fix crosses runtime, SDK, and publish workflows.
2. Defer `A03` until representative benchmark infrastructure is ready; do not start another optimization round from stale perf hypotheses.
3. Defer `A04` until product/ops ownership is ready to choose one CDC strategy instead of allowing connector drift.

## Sign-off

- All quick fixes applied: `yes` - the TA01 quick fix is already on `main` as `bbde79c`; TA10 did not introduce additional code fixes.
- All tickets created: `yes` - `8` new audit-created follow-up tickets exist (`T10..T14`, `T17..T19`), alongside the pre-existing `T06..T09`; `TA08` also references `6` Q2 architecture tickets (`A01..A06`).
- Memory + state synced: `yes` - `TA09` updated the baseline memory, and TA10 extends it to the final backlog and release verdict.
- CI status on final HEAD: `4/15 green`, `6/15 red`, `5/15 no-proof` - materially better understood than the `739ceb4` snapshot because `test-integration` now reaches real execution instead of failing during import/collection.
