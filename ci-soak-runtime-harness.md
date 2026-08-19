# CI Soak Runtime Harness

## Goal

Add a fail-closed local Compose runtime contract and Kubernetes-pods compatibility shim without changing any byte in the tracked source pack or claiming a soak result.

## Tasks

- [x] Add RED unit contracts for manifest rejection, ordered lifecycle commands, terminal-result finalization, cleanup, and identity-bound shim responses.
- [x] Implement `scripts/golden_soak/pods_shim.py` with bearer authentication, exact JM/TM container-ID binding, restart/health reporting, and bounded HTTP responses.
- [x] Implement `scripts/golden_soak/runtime.py` to validate the complete manifest before Docker, enforce the Compose start/baseline/observe/produce/verify sequence, record bounded evidence, and clean up in `finally`.
- [x] Launch the shim transiently with explicit read-only mounts (no static overlay change needed) and document the non-PASS boundary in the golden-soak README.
- [x] Review the scoped diff for fail-open paths and protect all eight pack hashes.
- [x] Run focused pytest, Ruff, `py_compile`, Compose config, and pack-hash gates; staged `git diff --check` is the commit gate.

## Done When

- [x] Focused tests prove failures cannot publish PASS, identity replacement/restart is unhealthy, manifest drift blocks Docker, and cleanup runs after success or failure.
- [x] All eight files under `scripts/golden_soak/pack/` retain their recorded SHA-256 values.
- [x] No workflow, container runtime rehearsal, push, remote action, or Mac gate claim is added.

## Mac Compose Rehearsal — 2026-08-19

One bounded `--count 2000` rehearsal used an exact archive of source commit
`8a77088dd6cfc802ca3fdf0c9ae0e7f3cce6079f` and the dedicated Compose project
`agentflow-ci-soak-8a77088-r2`. The controller ran with Python 3.13.7 against
`unix:///Users/julia/.colima/agentflow-fc5-7113966/docker.sock`.

The result is `FAIL`, not a rehearsal PASS:

- `result-final.txt` reports `RESULT=FAIL reason=one_shot_exit_nonzero`.
- `runtime-state.json` binds the failure to `iceberg-init`, which exited `2`.
- The captured service log reports `python: can't open file
  '/app/scripts/init_iceberg.py': [Errno 2] No such file or directory`.
- The file exists in the host snapshot and the saved container inspection binds
  that snapshot's `scripts` directory to `/app/scripts`. The Colima profile,
  however, shares only `/Users/julia/agentflow-fc5-7113966`; the rehearsal
  snapshot was under `/Users/julia` outside that shared root. This establishes a
  snapshot-placement/bind-visibility failure, not a failure in
  `scripts/init_iceberg.py`.

Cleanup and restoration passed independently. The rehearsal project has zero
containers, networks, and volumes. The exact pre-existing MinIO, Iceberg REST,
ClickHouse, and Kind container IDs are running again; MinIO and ClickHouse are
healthy, both HTTP APIs checked by the wrapper respond, Kind `/livez` responds,
and exactly one kube-apiserver is running. The original Mac checkout remains at
`ae9fb69db7de737b469f868f218e8d623c206959` with only its prior untracked paths.

Evidence remains on the Mac under
`/Users/julia/agentflow-ci-soak-rehearsal-8a77088-20260819-01/.artifacts/soak-rehearsal-2000-8a77088-r2`:

- `result-final.txt`: SHA-256
  `deafb12b95a1e0a5c319e1b9c5cfeb230c93fd189c3d4c1c17c56c8ccfad6ce4`.
- `runtime-state.json`: SHA-256
  `32d33a8e55bbb4f68a5f7cd5cd16eb953894c20d2da919cbe7c95bd9ce97e8b5`.
- `logs/inspect-iceberg-init.log`: SHA-256
  `2b41a4522bc7504bea5b8f07fee4e16af278f471b2d8006bda4c6d1fcc0dfecf`.
- `logs/collect-logs.log`: SHA-256
  `1f19ba53e90fe45da9781b778a572f333df11a54e47f7c8ec2563f66241cf701`.
- `logs/compose-down.log`: SHA-256
  `7b8d2bab76ac2d76cd60aff8fd3064ee47b3c83c977052bd955cff19109d6cd3`.

### Next-session resume contract

This subsection is the tracked source of truth for the next CI-soak session.
The latest blocks in ignored local files `AGENT_STATE.md` and
`docs/SESSION_HANDOFF.md` point here. Older workload-recovery handoffs describe
a different track and must not replace this resume contract.

#### Durable identifiers

| Item | Exact value |
| --- | --- |
| Rehearsed source commit | `8a77088dd6cfc802ca3fdf0c9ae0e7f3cce6079f` |
| First rehearsal-record commit | `b1c5f26c2463a04dab591d5704832b3d02d9c6c1` |
| SSH alias | `deproject-mac` |
| Docker socket | `unix:///Users/julia/.colima/agentflow-fc5-7113966/docker.sock` |
| Colima shared root | `/Users/julia/agentflow-fc5-7113966` |
| Evidence-only, unshared snapshot | `/Users/julia/agentflow-ci-soak-rehearsal-8a77088-20260819-01` |
| Preserved source archive | `<unshared snapshot>/source-8a77088.tar` |
| Source archive SHA-256 | `ed2c9c33b734304150ce8bcc1693b8aead963cc42906a603cbcc67fbe0dc8c1a` |
| Correct controller interpreter | `/usr/local/bin/python3` (`Python 3.13.7`) |
| Original user checkout | `/Users/julia/agentflow-docker-check` at `ae9fb69db7de737b469f868f218e8d623c206959` |
| Existing checkout state to preserve | `.codex-grok-tasks/`, `.venv-mac-docker/`, and `k8s/staging/values-staging-scale.yaml` are untracked |

Critical Git blob identities at the rehearsed commit are:

| Path | Git blob |
| --- | --- |
| `docker-compose.yml` | `a731a87a361466ded6c69620ee253d90b3fb8bd8` |
| `docker-compose.flink.yml` | `838ccf898e68f78f595cf6d0f46d67e6cb947fa6` |
| `docker-compose.soak.yml` | `53cdd51db73d61c9d45830cdcce9f975731bc7ec` |
| `scripts/golden_soak/runtime.py` | `522177a441db9c36900897c65749babd8755e5f8` |
| `scripts/golden_soak/pods_shim.py` | `e5cb97f506b949a9764f885bb13ca094b51d512d` |
| `scripts/init_iceberg.py` | `b5f9129a4b3ac6f8d45339a7afc60e65bf5a6934` |

`scripts/init_iceberg.py` has SHA-256
`226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`.
The next pre-stop bind probe must see this exact content from inside a
container attached to the target Docker daemon.

#### Attempt ledger

| Attempt | Wrapper | Outcome | Cleanup |
| --- | --- | --- | --- |
| `r1` | `<unshared snapshot>/run-rehearsal.sh`, SHA-256 `8ff0d29dd4b2f9871a8359adba7fa3bfbb206b0c5b06f38f8ecc0fb9266ee75e` | Selected `/usr/bin/python3` 3.9.6 and failed before Compose lifecycle; no terminal result file | `RESTORE_RESULT=PASS`; project resources `0/0/0` |
| `r2` | `<unshared snapshot>/run-rehearsal-r2.sh`, SHA-256 `565dd3d278186671c43b008e4c59d8fae51c92652489fa450fdaaa3d01268ab9` | Python 3.13.7 reached Compose; `iceberg-init` exited `2` because the unshared bind appeared without `init_iceberg.py` | `RESTORE_RESULT=PASS`; project resources `0/0/0` |

The `r2` failure occurred before producer, observer, or verification steps.
Do not describe it as an application, data-correctness, or soak failure.

#### Protected co-tenant baseline

The following state was independently verified after `r2`. Revalidate it
read-only in the next session; abort before any stop if an ID, name, label,
state, or port differs.

| Service | Exact container ID and name | Required restored state |
| --- | --- | --- |
| MinIO | `f51db9e3ee0715bbfc91c2a715a4fc114f80fdbe82e156e89db74626b729aa42`, `agentflow-iceberg-rv-20260802-01-minio-1` | running, healthy, ports `9000` and `9001` |
| Iceberg REST | `1e80588ca8fb0859934ada5635731027ca6692d9db597105504b1f7c2d761211`, `agentflow-iceberg-rv-20260802-01-iceberg-rest-1` | running, `/v1/config` responsive, port `8181` |
| ClickHouse | `a8cc630eedb5d116d605449771ea080c400ced742dc0540c44225897330c15b9`, `agentflow-ch-rv-20260802-01` | running, healthy, bind `172.18.0.1:8123` |
| Kind control plane | `0545702c4bc4ffdb5402b324af5dd51af71bed57ca7078707c931eae8aee365b`, `agentflow-reverify-ed03fc47-control-plane` | running, `https://127.0.0.1:50145/livez` responsive, exactly one kube-apiserver |

#### Required `r3` sequence

1. Confirm the local tracked tree and the original Mac checkout have no new
   changes. Preserve every unrelated untracked path. Confirm no writer or
   stale SSH process is active.
2. Revalidate the exact four-container baseline above and the target Docker
   socket. Do not stop anything during this step.
3. Require fresh, absent identities before creating them. Recommended names
   are snapshot
   `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-8a77088-r3`, Compose
   project `agentflow-ci-soak-8a77088-r3`, and output directory
   `.artifacts/soak-rehearsal-2000-8a77088-r3`. Do not adopt an existing path,
   project resource, or output directory.
4. Copy the preserved archive into the fresh shared-root snapshot, verify its
   SHA-256 before and after transfer, extract it, and verify the source commit
   identities listed above. The original checkout is not a staging area.
5. Before stopping co-tenants, use a disposable read-only bind probe on the
   exact Docker socket. It must read
   `/src/scripts/init_iceberg.py` from the new snapshot and match SHA-256
   `226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`.
   Remove the probe and confirm it left no resources. A failed probe ends the
   slice without a rehearsal.
6. Validate the merged Compose config, require zero resources for the new
   project, and require the new output path to be absent. Keep the established
   health `start_period` values and base healthcheck probes unchanged.
7. Derive `run-rehearsal-r3.sh` from the verified `r2` wrapper. Change only the
   shared snapshot path, new output path, and new project identity. Retain
   `/usr/local/bin/python3`, the Python >=3.11 guard, exact source-hash guards,
   exact co-tenant identity guards, and the unconditional cleanup/restore trap.
   Verify its SHA-256 and `bash -n` result on both hosts.
8. Only after every preceding gate passes may the wrapper stop the four exact
   co-tenants and invoke the controller once with `--count 2000`. Do not launch
   a parallel or duplicate run.
9. On exit, independently require the new project to have zero containers,
   networks, and volumes; require the four exact co-tenants and all health/API
   gates above; preserve and hash the terminal result, runtime state, init,
   producer, observer, verify, cleanup, and restoration evidence that exists.

#### Acceptance and stop conditions

A successful bounded run must exit `0` and begin its terminal line with:

```text
RESULT=REHEARSAL_PASS run=<identity> count=2000 gate=capacity-independent-rehearsal-only
```

It must not emit `RESULT=SOAK_PASS_DUAL_MEAN_90`. Even a rehearsal PASS closes
only the capacity-independent rehearsal gate; it does not close the Mac Kind
operator, HA, Helm rollback, traffic, full-soak, or production gates.

Stop without retrying in the same slice if the bind probe, identity baseline,
fresh-path checks, source hashes, Compose config, controller, cleanup, or
restoration gate fails. Preserve the evidence and report the first causal
failure. Do not rerun `r1` or `r2`, do not run from the unshared snapshot, do
not patch project code for the proven placement failure, do not touch the
original checkout's untracked files, and do not push.

### `r3` preflight-only attempt — 2026-08-19

The authorized `r3` slice did not invoke the rehearsal controller. Grok ran
through `local_grok_cli` with requested model `grok-4.6` and actual model
`grok-4.6-build`. The first run stopped at a headless permission boundary
before SSH. One cause-specific run added only the implicated read-only
PowerShell allow rules, then exceeded the six-poll execution budget without
producing its terminal JSON. Codex terminated that process tree once; no third
Grok run or controller retry was started.

The second run created the fresh shared-root snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-8a77088-r3`, copied and
extracted `source-8a77088.tar`, and stopped before creating either
`run-rehearsal-r3.sh` or `.artifacts/soak-rehearsal-2000-8a77088-r3`. The
archive SHA-256 remained
`ed2c9c33b734304150ce8bcc1693b8aead963cc42906a603cbcc67fbe0dc8c1a`;
all six critical Git blob identities matched the values above, and the
extracted `scripts/init_iceberg.py` SHA-256 remained
`226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`.
There is no durable evidence that the bind probe ran, so that gate is not
claimed.

Independent post-stop checks found no rehearsal/controller process and zero
containers, networks, or volumes for `agentflow-ci-soak-8a77088-r3`. The four
exact protected co-tenant IDs remained running with restart count zero; MinIO
and ClickHouse were healthy, MinIO's health endpoint passed, Iceberg REST
returned its `/v1/config` response, ClickHouse returned `SELECT 1`, Kind
`/livez` returned `ok`, and `docker top` showed exactly one
`kube-apiserver`. The original checkout remained at
`ae9fb69db7de737b469f868f218e8d623c206959` with only its three established
untracked roots. No tracked project code, push, full soak, traffic action, or
other remote resource was changed.

#### Next-session resume delta

The existing `r3` snapshot is evidence-only and must not be adopted or
overwritten. A later authorized rehearsal must start from fresh identities,
recommended as shared snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-8a77088-r4`, Compose
project `agentflow-ci-soak-8a77088-r4`, and output directory
`.artifacts/soak-rehearsal-2000-8a77088-r4`. Re-run every read-only identity,
hash, bind-visibility, Compose, and wrapper gate before stopping co-tenants.
The capacity-independent rehearsal gate remains open; push remains
unauthorized.

### `r4` one-shot rehearsal — 2026-08-19

The authorized `r4` slice used the fresh shared-root snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-8a77088-r4`, Compose
project `agentflow-ci-soak-8a77088-r4`, and output directory
`.artifacts/soak-rehearsal-2000-8a77088-r4`. The source archive, six critical
Git blob identities, and `scripts/init_iceberg.py` matched the durable values
above. A disposable container on the exact target Docker socket read the
expected init-script SHA-256 through a read-only bind. The merged Compose
config SHA-256 was
`9b0ead37ba3cdad9a6508908be11fe4d50083d0e666cf3c892698a894a96969b`.

`run-rehearsal-r4.sh` was derived from the verified `r2` wrapper by changing
only the snapshot, output, and project identities. Local and remote `bash -n`
passed, and both copies had SHA-256
`b3c4a61f282c9d7b3c80c0fe1ddbcefe2feb5d291fd4e1a1a7dd3ece836787a6`.
The wrapper invoked the controller exactly once with `--count 2000`; its
preflight passed and it stopped the four protected co-tenants before the
controller returned `1` with:

```text
RESULT=FAIL reason=up_app_failed
```

Builds, core startup, one-shot initializers, and data initialization all
completed successfully. `up-app` failed because Compose reported
`serving-bridge` as unhealthy. The service log shows that the bridge process
started normally and exposed metrics on port `9108`. The service has no
Compose-level healthcheck override, so its `agentflow-api-local:soak` image
supplies the API healthcheck for `http://127.0.0.1:8000/health/ready`, although
the bridge command does not start the API server on port `8000`. This is an
incompatible inherited healthcheck in the Compose contract, not a bridge
process crash, data-correctness result, or soak result. Producer, observer, and
verification steps did not run.

The wrapper reported `RESTORE_RESULT=PASS`. Independent checks on the exact
Colima socket found zero `r4` containers, networks, and volumes and no active
`r4` wrapper/controller process. The exact protected MinIO, Iceberg REST,
ClickHouse, and Kind IDs returned with restart count zero; MinIO and
ClickHouse were healthy, MinIO's health endpoint, Iceberg REST `/v1/config`,
and ClickHouse `SELECT 1` all passed. Kind `/livez` became responsive within
the bounded readiness wait, and `crictl` returned exactly one kube-apiserver
ID. The original Mac checkout
remained at `ae9fb69db7de737b469f868f218e8d623c206959` with only its three
established untracked roots.

Evidence remains under the `r4` output directory:

- `result-final.txt`: SHA-256
  `e4ce4bdc34a71615accbd319c33fdc2c87700a813f1d1cde5b8365fd0f76a699`.
- `runtime-state.json`: SHA-256
  `f1e4f4c407405ad38460bee9b4758ecfa82b230b07ca9fd2cfbf5f829d99caf3`.
- `logs/up-app.log`: SHA-256
  `8e4ea8833c4121ec016c4930913a510fb1d1bfeadf16283a361a974c67a94195`.
- `logs/collect-ps.log`: SHA-256
  `ffe8e0711114e3361d0a7ce50a739f7b16501b02cea96ceb423adf948568a346`.
- `logs/collect-logs.log`: SHA-256
  `ce2b1cf9ded6efd6675a03c02acc414e818cefcec594ba9aada3164649fa9f55`.
- `logs/compose-down.log`: SHA-256
  `140ad52faae96aaa0ddb955e454881f92b13e48aa3a90f199dfce883e132a9c5`.

#### Next-session resume delta

Treat the `r4` snapshot, project identity, wrapper, and output as immutable
evidence; do not adopt or rerun them. The local follow-up slice reproduced the
defect with a RED test against the merged three-file Compose config: both
`lake-materializer` and `serving-bridge` lacked service-level healthchecks.
`serving-bridge` now probes its own Prometheus endpoint on port `9108`, while
`lake-materializer`, which has no separate health endpoint, explicitly
disables the API image's inherited probe. The regression test turned GREEN;
the complete foundation/runtime unit gate reported `27 passed`, Ruff passed,
and `docker compose config --quiet` accepted the merged config. This local
verification does not claim a runtime rehearsal result.

Any later authorized rehearsal must use fresh identities, recommended as
shared snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-8a77088-r5`, Compose
project `agentflow-ci-soak-8a77088-r5`, and output directory
`.artifacts/soak-rehearsal-2000-8a77088-r5`. Re-run every pre-stop gate and
invoke the controller at most once. The capacity-independent rehearsal gate
remains open; no push, traffic test, full soak, or production gate is
authorized or claimed.
