# Auth 401/403 Spike

**Last updated:** 2026-05-24

## Symptom

One of:

- Every caller — including known-good integration test keys — starts receiving
  401 from `/v1/*` non-admin routes.
- A wave of 403 `PermissionDeniedError` from clients that worked an hour ago.
- `/v1/health` returns 200 but every other `/v1/*` route returns 503 with the
  body `"API key configuration is missing or empty"`.
- Synthetic auth probe (`tests/e2e/test_auth_smoke`) starts failing in
  scheduled CI.

## Severity

Default **Sev 1**. A blanket auth break locks every customer out of every route
and reads as a full outage from the client side.

## Owner

Platform / API on-call. Loop in Security if the trigger turns out to be a key
rotation or secret-mount change rather than a deploy.

## Detection

1. Grafana → AgentFlow / Auth panel:
   - `agentflow_auth_failures_total` by `reason` label
     (`missing_key`, `invalid_key`, `disabled_key`, `rate_limited`, `key_file_empty`)
   - 401/403 rate by route
2. Logs:
   ```
   {app="agentflow-api"} |= "AuthenticationError" or "PermissionDeniedError"
   {app="agentflow-api"} |= "auth" |= "fail-closed"
   ```
3. Verify the key file is actually present and non-empty inside a running pod:
   ```
   kubectl -n <ns> exec deployment/agentflow-api -- \
     sh -c 'ls -la $AGENTFLOW_API_KEYS_FILE && wc -l $AGENTFLOW_API_KEYS_FILE'
   ```
   Empty (0 bytes / 0 lines) or missing file → auth middleware is in
   fail-closed mode by design and will 503 every request.

## Triage

1. **`/v1/health` still 200?** If yes, the API process is up and the gate is in
   the auth middleware, not the network. If no, this is not an auth incident —
   go to `api-5xx-spike.md`.
2. **`AGENTFLOW_AUTH_DISABLED=true` was set in staging only?** Verify the
   variable is not leaking into production. Search Helm values:
   `git grep -nE 'AGENTFLOW_AUTH_DISABLED' helm/`
3. **Recent secret rotation?** Check audit log for changes to:
   - `kubectl -n <ns> get secret agentflow-api-keys -o yaml | grep dataHash`
   - Any `secret rotate` operation in the last 24h.
4. **Did the key file get truncated?** Compare `wc -l` against the previous
   known-good count in the runbook archive or the last deploy log. The audit
   incident on 2026-04-27 (`e8b1237`) was caused exactly by this — staging
   `api_keys` was set to `[]` empty list, fail-closed kicked in, every
   non-admin route 503'd while `/v1/health` kept returning 200 and masked the
   regression.
5. **Cross-tenant data?** If 403s look like tenant scoping, check the
   `tenant_id` column was populated on recent writes:
   ```
   kubectl -n <ns> exec deployment/agentflow-api -- \
     sh -c 'duckdb $AGENTFLOW_WAREHOUSE_PATH "SELECT DISTINCT tenant_id, count(*) FROM pipeline_events GROUP BY tenant_id"'
   ```

## Mitigation

### The api_keys file is empty or missing

Restore the previous known-good Secret manifest:

```
kubectl -n <ns> rollout undo deployment/agentflow-api
kubectl -n <ns> get secret agentflow-api-keys -o yaml > /tmp/now.yaml
# compare with the previous version in your secret store
```

Or, if the deploy rollback is not the right surface:

```
kubectl -n <ns> apply -f /path/to/last-known-good-api-keys.yaml
kubectl -n <ns> rollout restart deployment/agentflow-api
```

### Emergency bypass — non-production only

**Never use this in production.** If staging needs to keep functioning while
investigating, the documented opt-in is:

```
kubectl -n <staging-ns> set env deployment/agentflow-api AGENTFLOW_AUTH_DISABLED=true
```

Set a 1-hour reminder to remove it. Production environments must reject this
flag at deploy time — `helm/agentflow/values-prod.yaml` should not contain
`AGENTFLOW_AUTH_DISABLED` at all.

### Admin key revoked or rotated incorrectly

If admin operations themselves are returning 503, the admin key secret was
rotated without the deployment picking it up:

```
kubectl -n <ns> rollout restart deployment/agentflow-api
```

Then verify with:

```
kubectl -n <ns> exec deployment/agentflow-api -- \
  curl -sS http://localhost:8000/v1/admin/keys -H "X-Admin-Key: $ADMIN_KEY" | head -20
```

The admin route should return a key list with `key_hash` values but **never**
plaintext keys (verified in security boundary work `1c24e58` / `e8b1237`).

## Resolution

1. Confirm 401/403 rate is back to baseline for ≥ 10 minutes.
2. Confirm at least one known-good integration test key returns 200 from a
   non-admin endpoint:
   ```
   curl -sH "X-API-Key: $TEST_KEY" https://<api-host>/v1/entity/order/ORD-1
   ```
3. Confirm `AGENTFLOW_AUTH_DISABLED` is **not** set in production:
   ```
   kubectl -n <prod-ns> get deployment/agentflow-api -o yaml | grep -A1 AGENTFLOW_AUTH_DISABLED
   ```
4. File the incident with timeline, the broken Secret manifest (redacted), and
   the rollback artifact.

## Postmortem trigger

- Mandatory for any Sev 1 of any duration — auth incidents always get
  postmortems.
- Include a section "What detection signal would have caught this earlier?".
  The `/v1/health` exemption is intentional but it masks total-auth-failure
  from naive uptime monitors; the postmortem should produce a synthetic auth
  probe alert if one is not already wired up.
