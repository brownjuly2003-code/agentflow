<!--
Thanks for opening a pull request. See CONTRIBUTING.md for the full
expectations. This template captures the minimum a reviewer needs to
land the change confidently.
-->

## Summary

<!--
One paragraph (or 2-3 bullets) describing the user-visible change. Lead
with the "why" — what gap, regression, or use case prompted the patch.
-->

## Type of change

<!-- Tick all that apply. -->

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (existing behavior is intentionally changed)
- [ ] Documentation / hygiene only
- [ ] Performance change (please link benchmark evidence)
- [ ] Security change (please coordinate with maintainers — see SECURITY.md)

## Testing

<!--
Describe what you ran locally. Reviewers will not chase you down for the
test plan — say "n/a" with a reason if there is no real test surface.
-->

- [ ] `python -m pytest tests/unit tests/integration tests/sdk` passes
- [ ] `python -m ruff check src/ tests/` clean (only required if Python changed)
- [ ] TypeScript SDK: `cd sdk-ts && npm test` passes (only required if `sdk-ts/` changed)
- [ ] Helm chart: `helm lint helm/agentflow` and `helm lint helm/kafka-connect` clean (only required if `helm/` changed)
- [ ] Benchmark gate: `python scripts/check_performance.py ...` clean (only required for perf-sensitive paths)

## Checklist

- [ ] Conventional commit prefix used (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `perf:`, `style:`, `ci:`)
- [ ] `CHANGELOG.md` `[Unreleased]` section updated (skip for `docs:` and `chore:` PRs that do not change user-visible behavior)
- [ ] Public API surface changes have a matching update in `docs/api-reference.md`
- [ ] Operational behavior changes have a matching update in `docs/runbook.md` (local-dev) or `docs/runbooks/` (production on-call)
- [ ] Significant design choices have an ADR in `docs/decisions/`
- [ ] No new dependencies pinned beyond what the existing `[tool.agentflow.dependency-profiles]` block in `pyproject.toml` allows (workflow YAML is generated from this; do not hand-edit `.github/workflows/*.yml` for deps)

## Related

<!-- Issue numbers, prior commits, or external references. -->

Closes #
