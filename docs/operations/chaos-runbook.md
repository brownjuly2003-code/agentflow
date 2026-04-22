# Chaos Runbook

**Last updated:** 2026-04-22

## Purpose

This runbook covers scheduled and manually dispatched full chaos runs from `.github/workflows/chaos.yml`, triage steps when a failure issue is opened, and the fastest way to reproduce the failing scenario locally.

## Scheduled Workflow

- PRs run `tests/chaos/test_chaos_smoke.py` only.
- Scheduled and `workflow_dispatch` runs execute the full suite with `tests/chaos/test_chaos_smoke.py` excluded, because the repository does not define a dedicated `smoke` pytest marker.
- Failed full runs open a GitHub issue with labels `chaos-failure` and `severity:high`.

## When a scheduled chaos issue opens

1. Open the linked GitHub Actions run from the issue body.
2. Inspect the `Run chaos full suite` step first to identify the failing test node and scenario.
3. Download the `chaos-report` artifact and review:
   - `.artifacts/chaos/chaos-summary.md`
   - `.artifacts/chaos/chaos-summary.json`
   - `.artifacts/chaos/docker-compose.log`
4. Confirm whether the failure is product behavior, infrastructure instability, or a flaky dependency.
5. Reproduce locally before changing code or rerunning the workflow.
6. Update the issue with the suspected scenario, owner, and next action.

## Logs and Evidence

- GitHub Actions logs:
  - `Start chaos stack`
  - `Run chaos full suite`
  - `Generate chaos report`
  - `Collect compose logs`
- Local ports used by the chaos harness:
  - Toxiproxy API: `8474`
  - Kafka proxy: `19092`
  - Redis proxy: `16380`
- If you use GitHub CLI, `gh run view <run-id> --log` is the fastest way to inspect the failed step output.

## Local Reproduction

### Preferred local path

The `tests/chaos` fixtures already manage `docker-compose.chaos.yml`. From a clean environment, use the direct pytest command:

```bash
python -m pytest tests/chaos/ --ignore=tests/chaos/test_chaos_smoke.py -v --tb=short
```

Do not pre-start `docker-compose.chaos.yml` before this command unless you intentionally want CI-like behavior. Double startup can conflict on port `8474`.

### CI-like reproduction

Use this path when you need to mirror the workflow more closely:

```bash
mkdir -p .artifacts/chaos
export AGENTFLOW_CHAOS_CI_MODE=1
export AGENTFLOW_CHAOS_STARTUP_TIMEOUT=120
export PYTHONUNBUFFERED=1
docker compose -p agentflow-chaos -f docker-compose.chaos.yml up -d --wait --wait-timeout 120
python -m pytest tests/chaos/ --ignore=tests/chaos/test_chaos_smoke.py -v --tb=short --json-report --json-report-file=.artifacts/chaos/chaos-report.json
python scripts/chaos_report.py --input .artifacts/chaos/chaos-report.json --output .artifacts/chaos/chaos-summary.json --markdown .artifacts/chaos/chaos-summary.md
docker compose -p agentflow-chaos -f docker-compose.chaos.yml logs --no-color > .artifacts/chaos/docker-compose.log
docker compose -p agentflow-chaos -f docker-compose.chaos.yml down -v
```

If a future `make chaos-local` target is added, it should wrap this CI-like path. At the moment, no such Make target exists in the repository.

## Severity Escalation Matrix

| Severity | Trigger | Response target | Action |
|----------|---------|-----------------|--------|
| Sev 1 | Customer-facing regression or graceful-degradation path is broken in a core scenario and the issue reproduces locally | Immediate | Page the owning engineer, open incident handling, block risky deploys until understood |
| Sev 2 | Scheduled run fails in a core scenario, but impact is limited to resilience coverage or non-production paths | Same business day | Assign owner, reproduce locally, land fix or mitigation, rerun workflow |
| Sev 3 | Failure appears flaky, infra-related, or caused by transient GitHub runner problems | Next working day | Capture evidence, rerun once, create follow-up task if the failure repeats |

## Exit Criteria

- The failing scenario is identified.
- Reproduction notes are attached to the issue.
- A fix, mitigation, or flaky-test follow-up is assigned.
- The next scheduled or manually dispatched full chaos run completes successfully.
