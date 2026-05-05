# Codex + Kimi audit synthesis

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, 673 tracked files.

## Sources integrated

- Codex: `res/codex/co_res1d.md`, `res/codex/co_res2.md`, `res/codex/co_res3.md`, `res/codex/co_res4.md`, `res/codex/co_res5.md`.
- Kimi: `res/kimi/kimi_res1d.md`, `res/kimi/kimi_res2.md`, `res/kimi/kimi_res3.md`, `res/kimi/kimi_res4.md`, `res/kimi/kimi_res5.md`, `res/kimi/res_kimi.md`.

## Executive conclusion

High confidence: both research sets agree that M1/M2 are the first local remediation package. Global Ruff `S608` and Bandit `B608` suppressions should be removed, with existing reviewed SQL construction handled by scoped suppressions and baseline-diff verification.

High confidence: H4 and H5 remain external evidence gates. They cannot be closed from local code, internal docs, disabled workflows, or modeled plans.

Medium confidence: L6 and M7 are the next lowest-risk local changes after M1/M2. L6 is CI artifact generation only; M7 is staging rollback mechanics only. Neither proves production release readiness without operator evidence.

## Consensus matrix

| Item | Codex | Kimi | Synthesis |
| --- | --- | --- | --- |
| M1/M2 | First local package | First local package | Closed now with global suppressions removed and policy test added. |
| L6 | Local CI artifact gap | Immediate local CI work | Next safe local package after M1/M2. |
| M7 | Local staging rollback mechanics, prod evidence still needed | Immediate local rollback work | Safe as local staging-only hardening. |
| M3 | Local but staged; do not flip broad strictness until green | Immediate per-module strictness | Do a narrow green mypy slice first. |
| M8 | Do not raise global gate above current evidence without tests | Raise core gate after tests | Add tests before any higher gate. |
| H3 | Partial Helm guard only; architecture evidence still needed | Chart guard plus prod backend decision | Local guard is useful, full closure blocked on architecture/runtime evidence. |
| H6 | Separate architecture/key-management decision | Optional encrypted DuckDB path | Do not combine with H3/M4 until DuckDB production allowance is explicit. |
| M4 | Partial existingSecret support; owner evidence still needed | Combine with H3 Helm PR | Local chart support possible, production closure blocked on secret-source owner. |
| M9 | Needs architecture/evidence for immutability | Kafka audit dual-write | Architecture decision first; local mechanics alone do not prove immutable logs. |
| H4 | External owner evidence required | External AWS/OIDC owner required | Stay blocked. |
| H5 | External third-party attestation required | External pentest required | Stay blocked. |
| L7 | Blocked until container-release decision and registry digest | Skeleton possible, full closure external | Keep blocked unless container images are declared release artifacts. |

## Discord resolved

- Kimi groups L7 with CI/CD skeleton work. Codex separates L7 because signing without a published image digest and registry owner is only a skeleton. The safer current decision is to keep L7 blocked until container images are a release artifact.
- Kimi treats M3 as immediate broad strictness. Codex notes targeted mypy runs already expose substantial annotation debt. The safer path is a strict green slice, not a broad config flip.
- Kimi groups H3 and M4 because both touch Helm. Codex separates architecture/secret ownership from mechanics. The safe execution rule is: combine only if the same bounded Helm PR can stay render-only and has explicit owner decisions.

## Execution order from this synthesis

1. M1/M2: done in the current local package.
2. L6: done in the current local package.
3. M7: done in the current local package.
4. M3: done for the first narrow `src.quality.validators.*` strict slice.
5. M8: done for the first scoped `src.quality.validators` coverage gate.
6. H3/M4: Helm guardrails and existingSecret support only after choosing the exact render contract.
7. H6/M9: architecture decision first, implementation second.
8. H4/H5/L7: remain blocked on owner evidence or release-scope decisions.
