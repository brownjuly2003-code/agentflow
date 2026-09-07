# Deployment

This developer walkthrough helps choose a local or production-shaped path and
keeps the local entry commands. Exact Helm prerequisites, values, security and
scaling clauses, and rollout procedures belong to the
[complete Helm operator reference](operations/helm-deployment.md); the
[engineering status](STATUS.md) owns current evidence and external gates.
For the first executable local path, start with the
[quickstart](quickstart.md), then return here to choose another profile.

## Local demo with No Docker

Use this for the fastest local API, SDK, and documentation loop:

```bash
python scripts/demo_local.py
```

The runner selects a persistent DuckDB serving store, explicitly provisions and
seeds it, processes 500 events through the local pipeline, skips optional
Iceberg writes, and starts FastAPI on `http://localhost:8000`. It also disables
external Kafka, Flink, Iceberg, and Redis health/cache connections so this path
does not require local infrastructure after package installation.
The runner sets `AGENTFLOW_AUTH_DISABLED=true` for this local-only process;
keyed profiles must follow the
[API authentication contract](api-reference.md#base-url-and-headers).

Use `python scripts/demo_local.py --prepare-only` to stop after provisioning and
pipeline processing. `make demo-local` is a convenience alias.

## Docker demo

Use this when testing the ClickHouse-backed serving profile:

```bash
make demo
```

What it starts (see the `demo` target in the `Makefile`):

- Redis and ClickHouse through Docker Compose (ClickHouse is the default
  serving store — ADR 0006)
- an explicit provisioning step, `python -m agentflow_runtime.serving.provision --schema
  --seed` — the API itself never creates or seeds a store on boot (audit P0-2)
- synthetic event seeding through the local pipeline (500 events); the embedded
  DuckDB file keeps carrying the control-plane state
- FastAPI on `http://localhost:8000`

This path exercises more service boundaries than the local-only runner and
requires Docker Compose.

## Development compose

```bash
docker compose up -d
```

The default compose file includes Kafka, Flink, MinIO, Redis, Prometheus, and
Grafana. It is useful for pipeline and observability development, but it is not
a cloud production deployment.

## Production-shaped local stack

```bash
make stack-prod-shaped-local        # docker compose -f docker-compose.prod.yml up -d
make stack-prod-shaped-local-smoke  # prove a real authenticated request works
```

The stack models a more realistic topology:

- three Kafka brokers
- schema registry and Kafka UI
- Redis
- Jaeger
- optional ClickHouse profile
- FastAPI service container
- Prometheus, Alertmanager and Grafana

Use it for local debugging of service boundaries and observability wiring. It
is a demo, and the name says so: the Make target and the compose project name
are both `prod-shaped-local`, and `make stack-prod` now refuses with a pointer
here (audit F-09). What the topology does not model is a production security
posture -- plaintext Kafka, Redis and ClickHouse on loopback, dev credentials,
no TLS. The API runs with `AGENTFLOW_DEMO_MODE=true`, which the runtime refuses
to combine with `AGENTFLOW_PROFILE=production`, so this stack cannot be
relabelled into a production one by flipping a variable.
The same profile also refuses to boot without operator-supplied values for
`AGENTFLOW_QUERY_FINGERPRINT_PEPPER` (audit AF-13) and
`AGENTFLOW_KEY_LOOKUP_PEPPER` (audit FB-07): both built-in peppers are public
constants and are accepted on demo and dev only. Under Helm they are projected
from the operator-managed Secret through `extraEnv`, and the production values
contract refuses a render that omits either
([helm-deployment.md](operations/helm-deployment.md#pepper-material)).

The local auth contract is explicit: the API loads `config/api_keys.yaml` and
demo mode adds the published `demo-key`, so `/v1` routes answer 401 without a
key and 200 with one. Before, no auth settings were passed at all, every `/v1`
route fail-closed with 503, and the only thing ever checked was
`/health/ready` -- which is why the smoke target asserts all three: readiness,
a 401 for an anonymous read (a 503 there means the keys never loaded), and a
200 for an authenticated one.

Alerting is wired end to end, and honestly scoped. Prometheus loads the tracked
`monitoring/alerting/rules.yml` through
`monitoring/prometheus/prometheus.prod-shaped-local.yml` and delivers to a
local Alertmanager at <http://127.0.0.1:9093> that notifies nobody -- no email,
Slack, PagerDuty or webhook receiver. Rules written for the full pipeline
(freshness SLA, pipeline latency, Flink and Kafka health) stay loaded and stay
at "no data" here, because nothing in this stack produces those series.

Do not treat a compose stack as proof that a managed production environment has
been provisioned. A managed Kubernetes rollout follows the operator reference,
which owns chart and values paths, immutable image promotion, the fail-closed
production contract, and rollout verification.

## Managed Kubernetes boundary

The repository includes Helm and Kubernetes assets for staging-shaped workflow
rehearsal. They are intended to help operators render manifests, test chart
defaults, and prepare rollout work. A real environment still needs
operator-owned image promotion, secrets, ingress and TLS, capacity, monitoring,
rollback, and network isolation. This page carries that boundary and the
canonical public-prefix list below; the production contract's clause table
lives in the [Helm operator reference](operations/helm-deployment.md).

## Production ingress and `/metrics`

Prometheus scrapes `/metrics` in-cluster through the ClusterIP Service; the
endpoint is unauthenticated by design. A production Ingress
(`config.profile=production`) must not route it: the chart's production
contract rejects a values file whose host paths would send `/metrics` to the
API. Enumerate only the production path prefixes below instead of `path: /`
(or expose metrics on a separate internal-only host/ingress). Dev chart
defaults keep `path: /` and are unchanged.

```
/v1
/admin
```

The interactive documentation and schema paths are development surfaces, not
production ingress prefixes. With `config.profile=production`, the application
returns `404` for `/docs`, `/redoc`, and `/openapi*`; do not publish them through
the production Ingress. `/docs` and `/openapi.json` are auth-exempt outside
production, while `/redoc` follows the normal X-API-Key middleware.

`/health/live` and `/health/ready` are in-cluster-only for the same reason as
`/metrics`: kubelet probes dial the Pod IP and never traverse Ingress.
`/v1/health` is the public pipeline-health endpoint and is covered by `/v1`.

## Terraform overview

Terraform modules are present as reference infrastructure code. Local validation
can check syntax and module consistency, but applying to AWS requires external
setup that this docs build does not close:

- GitHub OIDC role bootstrap
- environment tfvars owned by the operator
- cloud account credentials and approval
- first real apply evidence

See the existing AWS OIDC setup handoff for the current status before making
any stronger infrastructure claim.

## External gates

| Gate | Current docs stance |
| --- | --- |
| AWS OIDC-backed Terraform apply | Not closed by this walkthrough |
| Third-party penetration test evidence | Not present in this walkthrough |
| Object-lock-backed immutable audit retention | Not evidenced by this walkthrough |
| Formal compliance certification | Not claimed |
| Production CDC source onboarding | Requires approved sources, secrets, network path, monitoring owner, and rollback owner |
