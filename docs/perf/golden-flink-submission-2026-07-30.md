# Golden Flink submission smoke — 2026-07-30

**Date:** 2026-07-30

**Exact commit:** `ca82be5a84a58ae37dd71ef80e785deb8e70dcad`

**Audience:** ops / developers recording live verification evidence

**Result:** **PASS** (submission smoke only)

## Goal and boundary

Prove that a **clean checkout** of the pinned PyFlink OCI definition builds on the
Mac Docker host and that a real Flink job can be **submitted and observed RUNNING**
via the Flink REST API.

### In scope

- Isolated clean checkout at exact HEAD
- Docker build of `src/processing/flink_jobs/Dockerfile`
- Scoped compose project bring-up for the local Flink stack
- Job submission and REST confirmation of `RUNNING` state
- Teardown with volume removal

### Non-goals (not claimed)

- kind cluster or Flink Kubernetes Operator deployment
- Helm golden-topology deployment
- Kafka → PyFlink → Iceberg → ClickHouse → API E2E
- Checkpoint restore / replay
- Soak / rollback rehearsal
- External pentest
- Production acceptance (`production.status` remains `candidate`)

## Baseline / environment

| Item | Value |
|------|-------|
| Route | local Grok CLI, profile `Grokw`, remote host `deproject-mac` |
| Isolated checkout | `/tmp/agentflow-acceptance-ca82be5-grokw-01` |
| Compose project | `agentflow-flink-ca82be5` |
| Docker client / server | 29.5.2 / 29.2.1 |
| Docker Compose | 5.1.4 |
| Flink | 2.3.0 (`c0f8d1a`) |
| Existing Mac checkout | unchanged (two prior untracked paths left in place) |

## Reproducible command classes

Absolute checkout and project names only; no secrets. Exact unpushed HEAD was
reproduced via a Git bundle from Windows `main` (not a remote `<repo-url>`
clone).

```bash
# 1) prepare isolated clean checkout at exact SHA (Windows -> Mac)
#    Windows source bundle:
#      D:\DE_project\.grok-prompts\agentflow-ca82be5-main.bundle
#    SCP to Mac:
#      /tmp/agentflow-ca82be5-main.bundle
git clone /tmp/agentflow-ca82be5-main.bundle \
  /tmp/agentflow-acceptance-ca82be5-grokw-01
cd /tmp/agentflow-acceptance-ca82be5-grokw-01
git checkout ca82be5a84a58ae37dd71ef80e785deb8e70dcad

# 2) compose prefix used for every live step below
#    (Homebrew docker on PATH; base compose + flink overlay; service flink-job-runner)
COMPOSE='docker compose --project-name agentflow-flink-ca82be5
  --project-directory /tmp/agentflow-acceptance-ca82be5-grokw-01
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.yml
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.flink.yml'

# 3) build PyFlink OCI image via compose service (not a direct docker build)
docker compose --project-name agentflow-flink-ca82be5 \
  --project-directory /tmp/agentflow-acceptance-ca82be5-grokw-01 \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.yml \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.flink.yml \
  build flink-job-runner

# 4) scoped bring-up of the job runner (and its compose dependencies)
docker compose --project-name agentflow-flink-ca82be5 \
  --project-directory /tmp/agentflow-acceptance-ca82be5-grokw-01 \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.yml \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.flink.yml \
  up -d flink-job-runner

# 5) observe submission markers in runner logs
docker compose --project-name agentflow-flink-ca82be5 \
  --project-directory /tmp/agentflow-acceptance-ca82be5-grokw-01 \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.yml \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.flink.yml \
  logs flink-job-runner

# 6) confirm via Flink REST (JobManager)
#    expect JobID + state RUNNING for agentflow-stream-processor

# 7) teardown with volume removal
docker compose --project-name agentflow-flink-ca82be5 \
  --project-directory /tmp/agentflow-acceptance-ca82be5-grokw-01 \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.yml \
  -f /tmp/agentflow-acceptance-ca82be5-grokw-01/docker-compose.flink.yml \
  down -v
```

Exact submission path matches the host smoke used on this run: compose service
`flink-job-runner` against the image built in step 3. Do not invent alternate
CI URLs or a direct `docker build` that was not part of the PASS run.

## Build evidence

| Item | Value |
|------|-------|
| Built image | `agentflow-flink-local:latest` |
| Image ID | `sha256:0796e98dc4f6d0cc38790910995d161fcf09a45db72da6d5eaffe5e554dc1004` |
| Image created | `2026-07-30T15:51:14.182834676+03:00` |
| Image size | 3.12 GB |

**Build recovery:** the first build tool call reached layer export, then the
headless shell timeout terminated the call. **One** narrowed safer retry reused
BuildKit cache and completed image export/tagging. This is **not** two
independent successful builds.

## Submission + Flink REST evidence

| Item | Value |
|------|-------|
| Submitted JobID | `e651fead82789ae20cb0935b3bccb513` |
| Job name / state | `agentflow-stream-processor` / `RUNNING` |
| TaskManagers | 2 |
| Slots total / available | 8 / 6 |
| Jobs running / failed | 1 / 0 |
| Vertices | both RUNNING |

## Recovered transient diagnostics

1. **Build timeout** — first tool call interrupted at export; single cache-reuse
   retry completed the image (see Build evidence).
2. **MinIO unhealthy on first `up`** — MinIO recovered; one
   dependency-continuation `up` started the runner. **No** image rebuild.

## Teardown and post-conditions

- Scoped compose `down -v` with project `agentflow-flink-ca82be5`, absolute
  `--project-directory`, and both base + flink compose files (see command classes)
- Zero containers remaining with the project label
- Existing Mac checkout left unchanged (two prior untracked paths untouched)

## Evidence log

| Item | Value |
|------|-------|
| Remote log path | `/tmp/agentflow-flink-smoke-ca82be5.log` |
| SHA-256 | `601312a48bf150ad5782864e510cc1ea28b8a01375e7c2305e339809a78d1c33` |

## Limits and next gate

This report closes only **clean-checkout OCI build + real job submission smoke**.

Still pending for golden-topology acceptance:

1. kind + Flink Kubernetes Operator + Helm deploy of the verified image
2. live Iceberg materialization from `events.validated`
3. Kafka → PyFlink → Iceberg → ClickHouse → API smoke
4. checkpoint restore and replay
5. 4 h soak and rollback on the golden topology
6. external pentest

**Next atomic gate:** clean kind cluster + Operator + Helm deployment of the
verified Flink OCI image. Do not raise `production.status` above `candidate`.
