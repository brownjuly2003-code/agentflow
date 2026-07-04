# Three-node demo — deploy runbook (owner-gated)

Publishes the three-node topology (ADR 0012 / `docs/three-node-demo-topology.md`)
as **three** Hugging Face Docker Spaces under the `liovina` account:

| Node   | Space                        | Role env       | Branch |
|--------|------------------------------|----------------|--------|
| Center | `liovina/agentflow-center`   | `center`       | `msk`  |
| Edge 1 | `liovina/agentflow-edge-spb` | `edge`         | `spb`  |
| Edge 2 | `liovina/agentflow-edge-ekb` | `edge`         | `ekb`  |

All three build the **same image** — the existing `deploy/hf-space/Dockerfile`,
tracking `main`. Role is pure environment set in each Space's **Settings**, not
in the image. The standalone `liovina/agentflow-demo` Space is unaffected; this
set is additive.

Each Space repo root gets two files: the shared `Dockerfile` and that node's
`README.md` (from `center/`, `edge-spb/`, `edge-ekb/` here).

## Deploy (outward — OWNER GATE)

Creating/pushing public Spaces under `liovina` is an external publish and is an
**owner gate**. The HF token lives in `D:/VacancyRadar/.env` (`HF_TOKEN`); never
print it. Bring-up order is **center first** — the edges need its URL live and a
matching `AGENTFLOW_NODE_TOKEN`.

Pick one strong shared token value for `AGENTFLOW_NODE_TOKEN` (same on all three;
store as a Space **secret**, never a variable, never logged).

```bash
# For each of: agentflow-center, agentflow-edge-spb, agentflow-edge-ekb
NAME=agentflow-center            # then edge-spb, edge-ekb
ROLEDIR=center                   # then edge-spb, edge-ekb

# 1. Create the Space (one-time)
huggingface-cli repo create "$NAME" --repo-type space --space_sdk docker

# 2. Push the shared Dockerfile + this node's README to the Space repo root
git clone "https://huggingface.co/spaces/liovina/$NAME" "/tmp/$NAME"
cp deploy/hf-space/Dockerfile "/tmp/$NAME/Dockerfile"
cp "deploy/hf-space/three-node/$ROLEDIR/README.md" "/tmp/$NAME/README.md"
cd "/tmp/$NAME" && git add Dockerfile README.md \
  && git commit -m "AgentFlow $NAME (three-node demo)" && git push
```

Then, in each Space's **Settings → Variables and secrets**, set the environment
from that node's README table:

- **Center:** `AGENTFLOW_NODE_ROLE=center`, `AGENTFLOW_NODE_BRANCH=msk`,
  `AGENTFLOW_DEMO_MODE=true`, `AGENTFLOW_SEED_ON_BOOT=true`; secret
  `AGENTFLOW_NODE_TOKEN`.
- **Edge spb / ekb:** `AGENTFLOW_NODE_ROLE=edge`,
  `AGENTFLOW_NODE_BRANCH=spb|ekb`,
  `AGENTFLOW_NODE_CENTER_URL=https://liovina-agentflow-center.hf.space`,
  `AGENTFLOW_DEMO_MODE=true`, `AGENTFLOW_SEED_ON_BOOT=true`; secret
  `AGENTFLOW_NODE_TOKEN` (same value as the center).

A misconfigured edge (no center URL or no token) fails its boot fast by design.

## Verify live (§12 of the build contract)

```bash
CENTER=https://liovina-agentflow-center.hf.space
SPB=https://liovina-agentflow-edge-spb.hf.space
EKB=https://liovina-agentflow-edge-ekb.hf.space
TOKEN=...   # the shared node token, from your secret store — never commit it

# 1. All three healthy
curl -fsS $CENTER/v1/health && curl -fsS $SPB/v1/health && curl -fsS $EKB/v1/health

# 2. Public demo-key cannot push (403 — demo-guard holds)
curl -i -X POST -H "X-API-Key: demo-key" -H "Content-Type: application/json" \
  -d '{"origin_branch":"spb","events":[]}' $CENTER/v1/node/events

# 3. Cross-branch view before any live event — silent branches show "waking"
curl -fsS -H "X-API-Key: demo-key" $CENTER/v1/node/branches

# 4. Open an edge (wakes it; its generator emits to the hub), wait, then re-read
#    the center view — that branch's live_delta is non-zero and last_seen is set.
curl -fsS $SPB/v1/health
sleep 30
curl -fsS -H "X-API-Key: demo-key" $CENTER/v1/node/branches
```

## Refresh after a repo change

Each Space tracks `main` (`ARG AGENTFLOW_REF=main`). Trigger a **Factory
rebuild** from the Space UI after a merge, or bump `AGENTFLOW_REF` to a tag for a
pinned demo.
