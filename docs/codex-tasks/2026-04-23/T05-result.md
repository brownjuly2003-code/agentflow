# T05 result — CI green audit (2026-04-23)

| Workflow | Status | Action | Run/Ticket |
|----------|--------|--------|------------|
| CI | red | quick fix prepared locally | 24809054294 |
| Contract Tests | green | — | 24804513712 |
| Load Test | red | needs ticket | T06-performance-workflows-baseline-repair.md |
| Security Scan | red | quick fix prepared locally | 24809054268 |
| Staging Deploy | red | quick fix prepared locally | 24809054272 |
| E2E Tests | red | quick fix prepared locally | 24809054282 |
| Backup | green | — | 24760679441 |
| Chaos | red | quick fix prepared locally | 24705766087 |
| DORA | green | manual dispatch | 24814675744 |
| Mutation | no recent run | needs ticket | T07-mutation-workflow-first-green-run.md |
| Performance | red | needs ticket | T06-performance-workflows-baseline-repair.md |
| Perf Regression | no recent run | needs ticket | T06-performance-workflows-baseline-repair.md |
| Publish NPM | no recent run | needs ticket | T08-sdk-publish-workflows-release-proof.md |
| Publish PyPI | no recent run | needs ticket | T08-sdk-publish-workflows-release-proof.md |
| Terraform Apply | no recent run | needs ticket | T09-terraform-apply-oidc-readiness.md |

## Notes

- Snapshot source: `origin/main` workflow history as of 2026-04-23 plus local T05 working-tree verification.
- `Acceptance` по remote `main` ещё не закрыт в этой сессии: quick fix-ы подготовлены локально, но не commit/push-нуты.
- Quick fixes prepared locally but not pushed in this session:
  - `CI`: local `ruff` is green, and `terraform fmt` was applied to the three files named by run `24809054294`.
  - `Security Scan`: local workflow keeps `ignore-unfixed: true` for Trivy.
  - `E2E Tests`: local workflow now uses `docker-compose.e2e.yml`; the lite stack starts locally and `/v1/health` responds instead of refusing the connection.
  - `Staging Deploy`: local staging values/script changes address the failing Helm rollout path and add diagnostics.
  - `Chaos`: local workflow now installs `.[dev,cloud]`, matching the missing `pyiceberg` import from the last failed run.
- Follow-up tickets were created only for workflows that still lack a green proof after this audit or need a separate PR/release event.
