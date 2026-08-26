# Deployment

AgentFlow has three useful local-to-production-shaped views. This page explains
what each view is for and where the external evidence boundary starts.

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
been provisioned. The production path is Helm: `helm/agentflow` with
`helm/agentflow/values-production.yaml` layered
under your environment values, which fails the render when the values still
carry dev posture. See the full
[Helm deployment reference](https://github.com/brownjuly2003-code/agentflow/blob/main/docs/operations/helm-deployment.md).

## Helm and Kubernetes

The repository includes Helm and Kubernetes assets for staging-shaped workflow
rehearsal. They are intended to help operators render manifests, test chart
defaults, and prepare cluster rollout work.

Before using them for a real environment, operators still need to provide:

- image registry plus build-once/promote-by-digest policy
- secrets and key ownership
- ingress/TLS strategy
- resource requests and limits
- monitoring ownership
- rollback process
- network isolation: set `networkPolicy.enabled=true` before any
  multi-replica production rollout (the chart default is `false` so
  kind/dev clusters without a NetworkPolicy controller keep working) and
  confirm the target cluster actually enforces NetworkPolicy

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
