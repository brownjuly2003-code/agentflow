# Admin key rotation

This page owns the procedure for replacing `AGENTFLOW_ADMIN_KEY`, the single
shared credential that guards `/v1/admin/*` — the routes that issue, rotate and
revoke every tenant API key. It covers when to rotate, the ordering that keeps
the analytics-retention job from failing, and how to confirm the old value is
dead. It does not cover tenant API keys, which have their own rotation path,
and it is not authorization to run anything against a production namespace.

**Audience:** Platform / API on-call and Security, during a scheduled rotation or after a suspected exposure

**Prerequisites:** write access to the Secret named by `secrets.existingSecret`, `kubectl` rollout rights in the namespace, and agreement on a window in which admin operations may fail

## What the admin key is

One value, shared by everyone who administers the deployment:

| Where | What holds it |
| --- | --- |
| Environment | `AGENTFLOW_ADMIN_KEY` |
| Secret | field `admin-key` of the Secret named by `secrets.existingSecret` |
| Consumers | the API and worker Deployments (`helm/agentflow/templates/_env.tpl`) and the analytics-retention CronJob (`helm/agentflow/templates/analytics-retention-cronjob.yaml`) |
| Enforced by | `require_admin_key` in `src/agentflow_runtime/serving/api/auth/middleware.py` |

Production installs set `secrets.create=false`, so the Secret is externally
managed and the [production contract](helm-deployment.md) refuses a render with
an empty `secrets.existingSecret`. Change the value in whatever system owns
that Secret, not in Helm values: values persist in release metadata and shell
history.

Two properties follow from it being *one* value, and both shape the procedure
below:

- **There is no dual-key window.** A pod validates against the single value it
  resolved at startup. During a rolling restart, old and new pods serve side by
  side, each accepting only its own key, so admin calls are unreliable until
  the rollout completes.
- **Every admin action is attributed to "someone with the key".** Per-operator
  admin credentials, hashed the way tenant keys already are, would remove both
  properties; they are not implemented, and rotation is what stands in for
  revoking one person's access.

## When to rotate

- On a schedule the deployment's own policy sets. This repository does not set
  one for you.
- Immediately, when the value has been anywhere it should not be: a ticket, a
  chat message, a CI log, a shell history, an unencrypted backup.
- When an operator who held it leaves, or their workstation is suspected
  compromised.
- After a burst of `admin_auth_failed` with `reason="admin_invalid"` from one
  address — someone is guessing it. Rotating does not stop the guessing, but it
  invalidates anything already learned.

The detection queries for that burst live in the
[auth 401/403 spike runbook](../runbooks/auth-401-spike.md).

## Rotate

1. **Generate the new value** where it will be stored, not on a shared host:

   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Do not echo it into a ticket, a commit, or this repository.

2. **Suspend the analytics-retention CronJob**, if it is enabled. Its pods read
   the Secret when they start and call `/v1/admin/analytics/retention`; a run
   that begins before the rotation and lands after it authenticates with the
   old value and exits non-zero (`restartPolicy: Never`, so the failure is
   final for that run and counts against `analyticsRetention.backoffLimit`):

   ```
   kubectl -n <ns> patch cronjob/agentflow-analytics-retention \
     -p '{"spec":{"suspend":true}}'
   kubectl -n <ns> get jobs -l app.kubernetes.io/component=analytics-retention
   ```

   Wait for any active job to finish before continuing.

3. **Update the `admin-key` field** in the system that owns the Secret, and
   wait for it to land in the namespace. Confirm the resource version changed
   without printing the value:

   ```
   kubectl -n <ns> get secret <existing-secret> -o jsonpath='{.metadata.resourceVersion}'
   ```

4. **Restart both Deployments.** Environment from a `secretKeyRef` is resolved
   at pod start and never refreshed, so an updated Secret changes nothing until
   the pods cycle:

   ```
   kubectl -n <ns> rollout restart deployment/agentflow deployment/agentflow-worker
   kubectl -n <ns> rollout status deployment/agentflow --timeout=5m
   kubectl -n <ns> rollout status deployment/agentflow-worker --timeout=5m
   ```

   Admin calls between the first restarted pod and `rollout status` returning
   are served by a mix of old and new pods. Treat a 401 during this window as
   expected, not as a failed rotation.

5. **Resume the CronJob:**

   ```
   kubectl -n <ns> patch cronjob/agentflow-analytics-retention \
     -p '{"spec":{"suspend":false}}'
   ```

## Verify

Run all three checks. The first two together are what distinguishes a completed
rotation from a half-applied one.

1. The new value is accepted:

   ```
   kubectl -n <ns> exec deployment/agentflow -- \
     curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/v1/admin/keys \
     -H "X-Admin-Key: $NEW_ADMIN_KEY"
   ```

   Expect `200`.

2. The old value is refused. Expect `401`, and expect one
   `admin_auth_failed` line with `reason="admin_invalid"` naming the caller's
   address — that line is the evidence the old credential is dead:

   ```
   {app="agentflow-api"} | json | event="admin_auth_failed"
   ```

3. The next retention run succeeds. Check the job that follows the next
   `analyticsRetention.schedule` tick, or trigger one:

   ```
   kubectl -n <ns> create job --from=cronjob/agentflow-analytics-retention \
     admin-key-rotation-check
   kubectl -n <ns> logs job/admin-key-rotation-check
   ```

   `HTTP 401` in those logs means the CronJob is still resolving an old Secret.

If admin routes return **503** rather than 401 afterwards, the pods resolved no
key at all: `admin_auth_failed` carries `reason="admin_unconfigured"`, and the
`admin-key` field is missing or empty in the Secret the pods actually mounted.
The [auth 401/403 spike runbook](../runbooks/auth-401-spike.md) owns that
incident.

## Record

Note who rotated, when, and the trigger — in the incident record for an
exposure, or the operations log for a scheduled rotation. Never record the
value itself, the previous value, or a prefix of either.

## What this does not cover

- **Tenant API keys.** They are hashed per key and rotated through the admin
  API itself (`scripts/rotate_key.py`, and the recovery guidance in the
  [disaster recovery runbook](disaster-recovery.md)). Rotating the admin key
  does not invalidate any of them.
- **The two digest peppers.** `AGENTFLOW_KEY_LOOKUP_PEPPER` and
  `AGENTFLOW_QUERY_FINGERPRINT_PEPPER` are separate material with a different
  blast radius — changing the first invalidates every stored `key_lookup`. See
  the [Helm deployment reference](helm-deployment.md).
- **Per-operator admin credentials.** Not implemented; see the property note
  above.
