# On-Call Runbooks

**Last updated:** 2026-05-24

This directory holds production-incident response runbooks for AgentFlow. The format and severity ladder are aligned with `docs/operations/chaos-runbook.md`.

## Scope

These runbooks assume AgentFlow is deployed via `helm/agentflow` (API + workers)
and `helm/kafka-connect` (CDC) in a real Kubernetes cluster, fronted by an
ingress and observed via Prometheus + Grafana + Jaeger. While production
onboarding is still gated on the inputs listed in
`docs/operations/cdc-production-onboarding.md`, these runbooks are the
authoritative response plan for when that gate opens.

The DV2 multi-branch demo cluster (Lima VM + kind, `hq-demo`) is **not** in
scope here — it has no on-call. Use `docs/dv2-multi-branch/SESSION_HANDOFF.md`
for that environment.

## Runbooks

| Symptom | File |
|---------|------|
| `/v1/*` error rate or 5xx spike | [api-5xx-spike.md](api-5xx-spike.md) |
| Sudden 401/403 wave across all callers | [auth-401-spike.md](auth-401-spike.md) |
| CDC lag, missing events, dead-letter growth | [cdc-lag.md](cdc-lag.md) |
| Load Test p99 gate fails on `main` | [load-test-regression.md](load-test-regression.md) |
| Bad version on PyPI / npm needs to be pulled | [release-rollback.md](release-rollback.md) |

## Severity ladder

This matches `docs/operations/chaos-runbook.md` so paging behavior is consistent
across all incident types.

| Severity | Trigger | Response target | Action |
|----------|---------|-----------------|--------|
| Sev 1 | Customer-facing regression: API down, data loss risk, auth break that locks every caller out, CDC stopped writing | Immediate | Page on-call, open incident channel, freeze deploys, follow the matching runbook |
| Sev 2 | Degraded path: p99 budget exhausted, partial endpoint down, single source CDC stuck, scheduled job failed | Same business day | Assign owner, mitigate, file follow-up |
| Sev 3 | Flaky signal: single transient 5xx, one chaos run flake, GH Actions runner glitch | Next working day | Capture evidence, rerun once, follow up if it repeats |

## Runbook format

Every runbook follows the same eight-section template so on-call can scan it
in under a minute:

1. **Symptom** — what the alert or pager actually says.
2. **Severity** — which row in the ladder above this defaults to.
3. **Owner** — team or person primary on this signal.
4. **Detection** — where to confirm the symptom (Grafana panel, log query, kubectl command).
5. **Triage** — first questions to rule scope in or out (which endpoint, which tenant, since when).
6. **Mitigation** — fastest known way to stop the bleeding while root cause is unknown.
7. **Resolution** — proper fix and the verification it actually worked.
8. **Postmortem trigger** — when this incident must produce a written postmortem (default: any Sev 1, any Sev 2 lasting > 4h).

## On-call protocol

- **Acknowledge** the page within 5 minutes. Acknowledgement does not require
  understanding — it only confirms a human is now looking.
- **Communicate** in the incident channel as you triage. Empty silence reads as
  "no one is on it" even when you are deep in `kubectl describe`.
- **Mitigate before you fix.** Roll back, scale up, fail over, throttle — get
  customer impact off the table before chasing root cause.
- **Mark severity at the top of the channel** and update it as you learn more.
  Sev 2 that turns out to be Sev 1 (data loss, secret leak) is fine; pretending
  it stayed Sev 2 is not.
- **Hand off explicitly** when your shift ends. A written status (current
  symptom, what you tried, what's pending) is mandatory before the next person
  picks up.

## When in doubt

If the symptom does not match any runbook here:

1. Check `docs/operations/chaos-runbook.md` — chaos scenarios cover most
   resilience-shaped failures (toxiproxy, Kafka isolation, Redis outage).
2. Check `docs/operations/cdc-production-onboarding.md` for CDC-specific
   preflight context.
3. Open the relevant Grafana dashboard and Jaeger trace search before paging
   anyone else — a 30-second look at the data usually disambiguates between
   "real outage" and "single bad client".
4. If you still cannot place the symptom, page Sev 2 with what you know and let
   the wider team triage.
