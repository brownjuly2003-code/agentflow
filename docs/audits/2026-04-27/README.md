# Audits — 2026-04-27

Two full audits delivered by the user on 2026-04-27 against HEAD `4a13d36`.

| File | Auditor | Scope |
|---|---|---|
| `audit_opus.md` | Claude Opus 4.7 (1M) | Strategic — overall 8.2/10, blockers map, BCG-style scorecard |
| `audit_codex.md` | Codex (combined p1–p9) | Detailed — architecture, auth/security, SQL, CI gates, test coverage, docker recovery, docs, TS SDK, Python SDK, supply chain |
| `audit_codex_parts/` | Codex per-section sources | Source files for the combined `audit_codex.md` |
| `cx-specs/` | This sprint | Self-contained CX task specs that drove the impl |

## Sprint outcome

Five commits closed all P0/P1/P2 findings:

```
e8b1237  security(W1): rotate webhook secret, fail-closed auth, scrub plaintext secrets
fb6aa14  hardening(W2/W3): helm posture, npm lockfile, openapi drift gate, doc fixes
1c24e58  security(W1): tenant isolation + SQL guard centralization + entity allowlist
d295ecf  test(W4): close 0% coverage on clickhouse_backend, freshness_monitor, producer
d61261b  sdk(W4): align Python SDK with server v1 contract (Codex audit p8 F1-F10)
```

Final smoke at `d61261b`: `670 passed, 4 skipped` on
`pytest tests/unit tests/integration tests/sdk tests/contract`.

## CX specs

- `cx-specs/cxkm_security_boundary.md` — drove `1c24e58` (tenant isolation +
  SQL guard + entity allowlist). CX run: `task-mohknyw3-dfyp2o`, 37m 23s.
- `cx-specs/cxkm_sdk_alignment.md` — drove `d61261b` (Python SDK F1–F10).
  CX run: `task-mohowalj-hefbeg`, 18m 47s.

Both specs are kept verbatim as a reference for future audit-driven sprints
on this repo: each follows a Goal / Context / Scope / Tests / Acceptance /
Notes-Constraints / Deliverables shape that produced applicable patches in
one Codex pass.
