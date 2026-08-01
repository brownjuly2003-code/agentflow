# Project closure

Дата фиксации scope: 2026-07-27.

## Закрываемый scope

Закрывается engineering scope AgentFlow:

- опубликованная линия v2 и измеренный Kafka → PyFlink → bridge → ClickHouse →
  API path;
- event/metric contracts, tenant-scoped serving, control-plane and webhook
  correctness;
- Python/TypeScript SDK capability contract;
- local DuckDB demo and existing release/security/quality gates;
- post-v2 golden-topology implementation как **production candidate**, а не
  production-acceptance claim.

После closing release этот scope feature-frozen. Production rollout и новые
breaking migrations требуют отдельной программы.

## Disposition untracked `plan_sol_23_07_26`

План сохранён локально без изменений. Его engineering core не остаётся
«непонятным WIP»:

| Шаг | Closing disposition |
|---|---|
| 1. Machine-readable claims | done (`config/project_claims.toml` + validator) |
| 2. Golden topology ADR/Helm | done as production candidate |
| 3. Fail-closed CDC tenant attribution | done |
| 4. Lake + serving materializers | done and component-tested |
| 5. TypeScript SDK parity | done for the verified common contract |
| 6. Reproducible install/CI | done for the local quality boundary |
| 7. Lifecycle/search robustness | done for declared local claims |
| 8. Session/control-plane split | done through role/capability boundaries |
| 9. Quality/docs/release controls | core done; external evidence remains below |
| 10. Production acceptance | separate external acceptance program |

Шаг 10 не объявляется выполненным. Clean-cluster Operator/Helm deploy of the
verified Flink OCI image on exact HEAD `36ed1ec` is measured
([perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md)),
and live Iceberg materialization from direct `events.validated` is measured at
the narrow boundary
([perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md)).
The remaining acceptance program still includes full Kafka → PyFlink → Iceberg
→ ClickHouse → API smoke, checkpoint restore/replay, fresh four-hour
golden-topology soak, rollback rehearsal and third-party penetration test.

## Post-closure future/accepted limits

- Golden-topology production acceptance — Operator/Helm deploy **PASS** on
  2026-07-30 and direct live Iceberg materialization **PASS** on 2026-08-01;
  full production acceptance remains `future operations`; production status
  remains `candidate`.
- Third-party pen-test and remediation/retest — required before a production
  security claim, not part of self-attested closure.
- P2-6 runtime namespace migration — `future breaking release`.
- Production CDC onboarding/credentials — `future deployment`.
- Transitive PyArrow advisory in the isolated Flink 2.3 image remains the
  documented upstream-blocked accepted risk and watchdog target.

## Обязательные внешние closure gates

- closing commits `59fc19c` (Operator/Kafka reproducibility) and `72b9609`
  (Python compatibility/core lock remediation), plus `f11fd59`
  (core-only/Ruff/runtime-image hardening), are published to `main`;
- all required GitHub checks green on the exact closing SHA;
- two open Dependabot PRs receive a final one-by-one disposition;
- the substantial post-v2 changes receive a final release/version decision and
  published supply-chain evidence if released.

Push, PR mutations and release actions require explicit owner authorization.

## Текущий closing handoff — 2026-08-01

- Python compatibility 3.11/3.12/3.13 is green on pushed SHA `72b9609`.
- The remaining main-CI failures on that SHA (Ruff 0.16 SDK Markdown and
  core-only API import without `pyiceberg`) are fixed and locally verified.
- The Security Scan findings were traced to packages vendored by runtime
  `pip`; the final image now removes installer tooling after `pip check`.
- CI on `f11fd59` passed every separate workflow and every early main-CI gate,
  then exposed two upstream-resolution boundaries: PyIceberg 0.11 writes
  without native core and MCP 2.0 breaking the 1.x integration API. The
  candidate now resolves `pyiceberg-core==0.7.0` across Python 3.11–3.13 and
  constrains MCP to `<2`; `2170` local unit/property tests and all `39`
  selected clean-Mac dependency tests pass. See
  [dependency-compatibility-2026-07-30.md](dependency-compatibility-2026-07-30.md).
- Independent Mac image validation reports zero HIGH/CRITICAL findings with
  Trivy 0.70.0; see
  [security-runtime-image-trivy-2026-07-30.md](security-runtime-image-trivy-2026-07-30.md).
- On 2026-08-01 the owner explicitly re-enabled Grok as implementation
  executor; Codex orchestrates and verifies. Live Iceberg materialization from
  direct `events.validated` is **PASS** at the narrow boundary — see
  [perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md).
- Repository-owned coverage gates are green and remain blocking. Codecov OIDC
  currently returns `Repository not found`; its upload is non-blocking
  reporting until the one-time external activation in
  [operations/codecov-setup.md](operations/codecov-setup.md) is completed.
- Production status remains `candidate`; five production gates remain open:
  full Kafka → PyFlink → Iceberg → ClickHouse → API smoke, restore/replay,
  fresh soak/rollback, external pen-test, and npm approval evidence.

## Сохранённые локальные артефакты

Root `AGENTS.md` and `plan_sol_23_07_26` remain untracked and unchanged. They do
not enter the public closing commit.
