# API 5xx Spike

**Last updated:** 2026-05-24

## Symptom

Grafana panel `agentflow / API 5xx rate` crosses 1% sustained for ≥ 2 minutes,
or one or more of:

- `agentflow_http_requests_total{status=~"5.."}` rises sharply.
- `/v1/entity/*`, `/v1/metrics/*`, `/v1/query`, or `/v1/batch` returns 500/502/503
  to a customer who is not posting malformed input.
- Synthetic probe (`scripts/healthcheck.py` / external uptime monitor) fails on
  `/v1/health` twice in a row.

## Severity

Default **Sev 1** if the 5xx rate is ≥ 5% or `/v1/health` is failing for any
caller. Default **Sev 2** if a single endpoint family is degraded and other
endpoints are healthy.

## Owner

Platform / API on-call. Escalate to Data on-call if the error chain points at
the warehouse (DuckDB / ClickHouse) rather than the API layer.

## Detection

1. Grafana → AgentFlow / API overview → panels:
   - 5xx rate by route
   - Latency p50/p95/p99 by route
   - Pod restart count (last 1h)
2. Logs (Loki / structured JSON):
   ```
   {app="agentflow-api"} |= "level=error"
   {app="agentflow-api"} |= "status" |= "503"
   ```
3. Jaeger: filter by service `agentflow-api`, tag `http.status_code=5xx`,
   sort by duration descending.
4. Kubernetes:
   ```
   kubectl -n <ns> get pods -l app.kubernetes.io/name=agentflow
   kubectl -n <ns> top pods -l app.kubernetes.io/name=agentflow
   kubectl -n <ns> describe pod <pod>
   ```

## Triage

Answer these in order — they cut the search space fastest:

1. **Which routes?** Single route family (only `/v1/query`) vs. fan-out across
   all routes. Single family points at backend; fan-out points at API layer,
   ingress, or shared resource (Redis, auth, DB pool).
2. **Which tenants?** If a single tenant is generating all the 5xx, this is
   most likely bad client traffic — see `Mitigation → Throttle a single tenant`.
3. **Started when?** Compare the spike start with `gh run list --workflow ci.yml
   --limit 10` and the deploy timeline in Grafana annotations. A spike that
   starts within minutes of a deploy is almost always the deploy.
4. **Logs say what?** Look for the first 5 unique exception classes in the last
   10 minutes. `BackendExecutionError`, `RateLimitExceeded`, `AuthenticationError`,
   `TimeoutError`, `ConnectionResetError` each have distinct root causes.
5. **Pods healthy?** Any pod in `CrashLoopBackOff`, `OOMKilled`, or with restart
   count climbing in the last 30m.

## Mitigation

Do the cheapest reversible thing first.

### Recent deploy is the suspect

```
kubectl -n <ns> rollout history deployment/agentflow-api
kubectl -n <ns> rollout undo deployment/agentflow-api
kubectl -n <ns> rollout status deployment/agentflow-api --timeout=3m
```

After rollback verify the 5xx panel drops within one scrape interval (15-30s).
If it does not, the deploy was not the cause — keep the rollback for safety,
continue triage.

### Pod resource exhaustion (OOM / CPU throttle)

Temporary scale-out:

```
kubectl -n <ns> scale deployment/agentflow-api --replicas=<current+2>
```

Then check HPA state (`kubectl -n <ns> get hpa`) and consider raising the upper
bound. Permanent fix lives in `helm/agentflow/values-<env>.yaml`
(`resources.requests` and `autoscaling.maxReplicas`).

### Throttle a single tenant

If one API key / tenant is generating the spike:

```
kubectl -n <ns> exec deployment/agentflow-api -- \
  curl -sS -X POST http://localhost:8000/v1/admin/keys/<key_id>/rate-limit \
  -H "X-Admin-Key: $ADMIN_KEY" -d '{"requests_per_minute": 10}'
```

`/v1/admin/keys/*` is admin-only and requires `X-Admin-Key`. Configure the
admin key via `AGENTFLOW_ADMIN_KEY` (Helm `secrets.adminKey`).

### Backend exhausted (DuckDB / ClickHouse pool starved)

Symptoms: `BackendExecutionError`, p99 latency spike that precedes the 5xx wave,
DB pool gauges at 100%.

- Restart the API deployment to reset connection pools:
  ```
  kubectl -n <ns> rollout restart deployment/agentflow-api
  ```
- If the warehouse itself is the bottleneck (CPU / IO saturated), throttle
  inbound write rate via the dispatcher: scale down `agentflow-batch-worker`
  replicas temporarily.

## Resolution

1. Confirm the 5xx panel is back under 0.5% for ≥ 10 minutes.
2. Confirm `/v1/health` returns 200 on every replica:
   ```
   for p in $(kubectl -n <ns> get pods -l app.kubernetes.io/name=agentflow -o name); do
     kubectl -n <ns> exec $p -- curl -sf http://localhost:8000/v1/health
   done
   ```
3. Confirm Jaeger traces in the last 5 minutes have `http.status_code` ≤ 2xx
   for the affected routes.
4. Open a follow-up issue with label `incident-followup` containing: timeline,
   root cause, mitigation steps applied, permanent fix proposal.

## Postmortem trigger

- Mandatory for Sev 1 of any duration.
- Mandatory for Sev 2 lasting > 4 hours or affecting > 1 tenant.
- Postmortem template: copy `docs/lessons/ci-repair-sprint-2026-04.md` as a
  structural starting point (Lesson / Apply / Concrete-trace SHA format works
  here too).
