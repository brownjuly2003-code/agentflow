# Chaos Runbook

**Updated:** 2026-08-31

This page owns the full chaos workflow in `.github/workflows/chaos.yml`, the
steps after a `chaos-failure` issue opens, and the local path that reproduces
the failing scenario. It does not inventory other operations procedures —
those live in [README.md](README.md).

**Audience:** maintainer triaging a chaos-workflow failure issue

**Prerequisites:** GitHub access to the failed `chaos.yml` run and the `chaos-report` artifact, Docker Compose for `docker-compose.chaos.yml`, pytest for `tests/chaos/`, and `scripts/chaos_report.py`

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

### Report CLI ownership

`python scripts/chaos_report.py` defaults its input to ignored
`.artifacts/chaos/chaos-report.json` owned from the project root. Relative
`--input`, `--output`, and `--markdown` paths also resolve from the project
root; absolute paths remain supported. Optional JSON and Markdown outputs
create parent directories and are written as UTF-8 with LF newlines.

The CLI only summarizes an existing pytest JSON report. It does not start
Docker, Toxiproxy, or the chaos suite, and it does not change workflow
triggers, artifact names, teardown, or issue behavior. Missing input exits 1
after emitting the missing-status report. When `--markdown` is omitted,
Markdown still goes to stdout.

Do not treat `chaos-report.json`, `chaos-summary.json`, or `chaos-summary.md`
at the repository root as canonical. These files are host/time/test-run
dependent runtime evidence, not a tracked current reference and not a
byte-regenerated production acceptance artifact. Promote a reviewed snapshot
only under a new date-stamped identity with source SHA, scenario/configuration,
host/runtime, exact command, result counts, and artifact hashes.

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
