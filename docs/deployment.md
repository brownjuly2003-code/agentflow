# Deployment

AgentFlow has three useful local-to-production-shaped views. This page explains
what each view is for and where the external evidence boundary starts.

## Local demo

Use this when developing the API, SDK examples, or documentation.

```bash
make demo
```

What it starts:

- synthetic event seeding through the local pipeline
- DuckDB demo database
- Redis through Docker Compose
- FastAPI on `http://localhost:8000`

This path is intentionally small. It is the fastest way to test entity lookup,
metrics, natural-language query, and SDK calls.

## Development compose

```bash
docker compose up -d
```

The default compose file includes Kafka, Flink, MinIO, Redis, Prometheus, and
Grafana. It is useful for pipeline and observability development, but it is not
a cloud production deployment.

## Production-shaped compose

```bash
docker compose -f docker-compose.prod.yml up -d
```

The production-shaped compose stack models a more realistic topology:

- three Kafka brokers
- schema registry and Kafka UI
- Redis
- Jaeger
- optional ClickHouse profile
- FastAPI service container
- Prometheus and Grafana

Use it for local debugging of service boundaries and observability wiring. Do
not treat a compose stack as proof that a managed production environment has
been provisioned.

## Helm and Kubernetes

The repository includes Helm and Kubernetes assets for staging-shaped workflow
rehearsal. They are intended to help operators render manifests, test chart
defaults, and prepare cluster rollout work.

Before using them for a real environment, operators still need to provide:

- image registry and tag policy
- secrets and key ownership
- ingress/TLS strategy
- resource requests and limits
- monitoring ownership
- rollback process

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
