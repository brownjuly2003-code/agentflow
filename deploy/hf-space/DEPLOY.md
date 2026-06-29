# Hugging Face Docker Space — deploy runbook

Publishes the read-only demo (`Dockerfile` + `README.md` in this directory) as a
Hugging Face Docker Space. The Space builds the image itself from the public
GitHub repo, so only these two files are pushed to the Space repo.

## Local / Mac build verification (do this before deploying)

Docker is Mac-only in this setup (Windows does not run the daemon). The build
context is this directory; the repo is cloned inside the image.

```bash
docker build -t agentflow-hf deploy/hf-space
docker run --rm -p 8000:8000 agentflow-hf &
sleep 25
curl -fsS http://localhost:8000/v1/health
curl -fsS -H "X-API-Key: demo-key" http://localhost:8000/v1/entity/order/ORD-20260404-1001
```

## Deploy (outward — gated)

Creating/pushing a public Space under the `liovina` account is an external
publish. The HF token lives in `D:/VacancyRadar/.env` (`HF_TOKEN`); never print it.

```bash
# 1. Create the Space (one-time)
huggingface-cli repo create agentflow-demo --repo-type space --space_sdk docker

# 2. Push the two files to the Space repo root
#    (clone the Space repo, copy Dockerfile + README.md, commit, push)
git clone https://huggingface.co/spaces/liovina/agentflow-demo /tmp/agentflow-space
cp deploy/hf-space/Dockerfile deploy/hf-space/README.md /tmp/agentflow-space/
cd /tmp/agentflow-space && git add Dockerfile README.md \
  && git commit -m "AgentFlow read-only demo (docker sdk)" && git push
```

The Space builds the Dockerfile and serves on `app_port: 8000`. Live URL:
`https://liovina-agentflow-demo.hf.space`.

## Verify live

```bash
curl -fsS https://liovina-agentflow-demo.hf.space/v1/health
curl -fsS -H "X-API-Key: demo-key" \
  https://liovina-agentflow-demo.hf.space/v1/entity/order/ORD-20260404-1001
```

## Refresh after a repo change

The Space tracks `main` (`ARG AGENTFLOW_REF=main`). Trigger a rebuild from the
Space UI ("Factory rebuild"), or bump `AGENTFLOW_REF` to a tag for a pinned demo.
