# CI Soak Runtime Harness

> **Next-session entry point:** use the tracked
> [CI-soak next-session runbook](docs/operations/ci-soak-next-session-runbook.md)
> for current status, consumed identities, authorization boundaries, and the
> exact cold-start sequence. The chronological material below is supporting
> history.

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

### `r5` one-shot rehearsal — 2026-08-19

The authorized `r5` slice used a fresh archive of source commit
`4e25e392b9da52d1b7b0f44a4a0dd35bcb0240cf` in shared-root snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-8a77088-r5` with Compose
project `agentflow-ci-soak-8a77088-r5`. The source archive SHA-256 was
`a220a015b0d7e2f9fd07a97197bbbc8e724a6bcefdafd4af9daee22f50515b01`;
all six critical Git blobs matched local HEAD, and the read-only bind probe saw
the expected init-script SHA-256. The merged Compose config SHA-256 was
`68253801857d5fe02f700c266ea76cb2079afa9017d1be9ca8c96cfda95bc6f6`
and contained the corrected background-consumer healthchecks.

`run-rehearsal-r5.sh` differed from the verified `r4` wrapper only in the
snapshot, output, project, archive filename, and archive hash. Local and
remote `bash -n` passed, and both copies had SHA-256
`b732eb9ce670425eae2ef65d4732a87d112c56018fc0945e73b17f7630565dc2`.
The wrapper invoked the controller exactly once with `--count 2000`. Its
preflight passed, it stopped the four protected co-tenants, and the controller
returned `1` with:

```text
RESULT=FAIL reason=shim_container_id_invalid
```

The prior healthcheck defect is no longer the first failing gate: `up-app`
returned `0`, the Flink runner started, both Flink containers were running
with restart count zero, and the Flink gate saw four tasks and one completed
checkpoint with no failed checkpoints. The failure occurred immediately after
the detached shim container was created and before shim probe, baseline,
observer, producer, or verification.

The two Flink IDs in `ps-jm.log` and `ps-tm.log` are valid 64-character IDs.
The `shim-start.log` output, however, contains two Docker Compose progress
lines followed by the valid 64-character shim ID. `SubprocessRunner` merges
stderr into stdout, while `_start_shim()` applies the container-ID regex to
the complete stripped multi-line output. Docker Compose 5.1.4 therefore makes
the controller reject its own successful detached start. `_start_observer()`
uses the same whole-output parsing pattern and has the same latent defect.
This is a controller output-parsing failure, not a shim, Flink, application,
data-correctness, or soak failure.

The wrapper reported `RESTORE_RESULT=PASS`. Independent checks found zero
`r5` containers, networks, and volumes and no active `r5` process. The exact
four protected container IDs returned running with restart count zero; MinIO
and ClickHouse were healthy, all required API checks passed, and exactly one
kube-apiserver was running. The original Mac checkout remained at
`ae9fb69db7de737b469f868f218e8d623c206959` with only its established
untracked roots.

Evidence remains under
`<r5 snapshot>/.artifacts/soak-rehearsal-2000-8a77088-r5`:

- `result-final.txt`: SHA-256
  `76dc9b2078225585348671d6456eba77c56d839c52e2d63b93574e4fa6ab0966`.
- `runtime-state.json`: SHA-256
  `cb8bf505e7f7a03190cd14f4a3b2d5f94c2b9d822470a026c820b44aa0865752`.
- `logs/shim-start.log`: SHA-256
  `1afa8a13d54f1f96ff5524d107c98592bd969910709819d6bcbbb693a3a36756`.
- `logs/ps-jm.log`: SHA-256
  `08353a6f8e5bc190abaa4da33c3809fb9929e3260daaee3830bbfdede5aab6ad`.
- `logs/ps-tm.log`: SHA-256
  `5bc6f1b92fd501d8b18fd36fc24fd2d7ddae0b4a615ccecef09fa4a3c61e8c38`.
- `logs/up-app.log`: SHA-256
  `37126fa980293ee99c4ccbc2bb50da51b14d04f6e77bde778bba7483d750cf72`.
- `logs/collect-logs.log`: SHA-256
  `ee9b361d4a67ff34c5984269c75661bb8f1c581cda13505217736ae46a57a61b`.
- `logs/compose-down.log`: SHA-256
  `4afd85a2eb4cc11a3afc23a005f5533bcf9b16a8da00698dd0d60c2ce96a63e0`.

#### Next-session resume delta

Treat every `r5` identity and artifact as immutable evidence; do not rerun or
adopt them. Commit `d20379e5781b9d6d1fc3a6f609d0c64f368b97e7`
separates `SubprocessRunner` stdout and stderr, makes controller decisions from
stdout, preserves both channels in bounded step logs, and uses one shared
parser for shim and observer starts. The parser accepts exactly one full
64-lowercase-hex line within noisy output and fails closed for zero, multiple,
partial, or embedded IDs. Timeout and OS-error evidence remain on stderr.

The regression was confirmed RED against the `2cc4326` implementation: the
runner returned the merged value `progress\nmachine\n` and exposed no separate
stdout. Grok then completed the local implementation pass through
`local_grok_cli` (RunId `de-ci-soak-r5-channel-20260820-grok01`, requested
model `grok-4.6`, actual model `grok-4.6-build`); its focused result was
`28 passed`. Independent verification reported `36 passed` across the runtime
and foundation contracts. Ruff check, changed-path Ruff format, `py_compile`,
staged `git diff --check`, protected-file hashes, and the stale `.output`
consumer search also passed.

No Docker lifecycle or new Mac rehearsal ran in this local correction slice;
the Mac SSH endpoint timed out before any remote command executed. A later
authorized rehearsal must use fresh `r6` identities and a new archive of its
exact source HEAD. The capacity-independent rehearsal gate remains open; no
push, traffic test, full soak, or production gate is authorized or claimed.

### `r6` one-shot rehearsal — 2026-08-20

The authorized `r6` slice rehearsed exact source commit
`5a1a3d10af082e88db0f74ee84da2b1627c072e5` from fresh shared-root snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-5a1a3d1-r6`, Compose
project `agentflow-ci-soak-5a1a3d1-r6`, and output directory
`.artifacts/soak-rehearsal-2000-5a1a3d1-r6`. The source archive SHA-256 was
`d60fea21fc83a174008a4121d3dffc6797c8aa27f084e4481e3205d66efc937e`.
The exact source commit, all six critical Git blobs, runtime SHA-256
`d4caf88cddca875e5da64060eeb33f7447462a192cd9269250b1e4241426df4d`,
and init-script SHA-256
`226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`
matched before any co-tenant stop. A cached-image read-only bind probe saw the
init script through the exact target Docker socket, and the merged Compose
config SHA-256 was
`9f67cb0c0e8240e7f89a0a0b0d590003fa6de8adbe74fd615704827fcde44d7d`.

`run-rehearsal-r6.sh` was derived from the immutable `r5` wrapper by changing
only the snapshot, output, project, archive filename, archive hash, and runtime
hash. Local and remote `bash -n` passed, and both copies had SHA-256
`1bb0c90be770adb1dc3037a751fa19ab33b17b572ffe9205811557782042b55c`.
The wrapper invoked the controller exactly once with `--count 2000`; it
reported `PREFLIGHT_RESULT=PASS`, stopped the four protected co-tenants, and
the controller returned `1` with:

```text
RESULT=FAIL reason=shim_probe_failed
```

The `r5` channel/parser correction worked: `shim-start.log` contains one valid
64-character stdout ID,
`4d9f751397c26170c6d9335e2cccfd8f8e56e7169cffb65d0a47abf6b22038bf`,
while Docker Compose progress remained on stderr. Both builds, core and app
startup, all identity-bound one-shot gates, Flink startup, four-task readiness,
and the initial checkpoint gate passed. The failure occurred before baseline,
observer, producer, or verification. All 16 shim-probe attempts returned one;
the final probe evidence ends with:

```text
FileNotFoundError: [Errno 2] No such file or directory: '/shim/token'
```

This is a confirmed macOS/Colima bind-visibility defect in the controller.
`_prepare_tls()` creates the token and TLS files with unqualified
`tempfile.mkdtemp()`. On this Mac, Python therefore selected
`/var/folders/.../T/<project>-shim-*`, outside the Colima profile's shared
`/Users/julia/agentflow-fc5-7113966` root. Both `_start_shim()` and
`_probe_shim()` correctly requested a read-only `/shim` bind, but the daemon
inside the VM materialized that unshared host source as an empty directory.
A bounded comparison on the same Docker socket proved the boundary: a marker
under Python's `/var/folders/...` default returned `MISSING`, while a marker
under `/Users/julia/agentflow-fc5-7113966` returned `VISIBLE`. The shim
container was consequently observed exited `1`, and the transient probe could
not read its token. This is not a Docker outage, service-readiness failure,
application/data-correctness result, or soak result.

The wrapper reported `RESTORE_RESULT=PASS`. Independent checks on the exact
target socket found zero `r6` containers, networks, and volumes and no active
wrapper/controller process. All four exact protected IDs were running with
restart count zero; MinIO and ClickHouse were healthy, MinIO and Iceberg REST
returned HTTP `200`, ClickHouse returned internal `Ok.`, Kind `/livez`
returned `ok`, and `crictl` found exactly one kube-apiserver. The original Mac
checkout retained only its three established untracked paths; no tracked file
there was changed.

Evidence remains under
`<r6 snapshot>/.artifacts/soak-rehearsal-2000-5a1a3d1-r6`:

- `result-final.txt`: SHA-256
  `ede962f78adfac89a7e965d3944e67e13b8e1b88223a76981c077e15a4481c44`.
- `runtime-state.json`: SHA-256
  `085a6f1ab1b83a082fb88871b975ddc4e2c94b377aa67354adb95e2bddf39a60`.
- `logs/shim-start.log`: SHA-256
  `2b074ebb60efbb49d07f09b1f518e6e465fbcc4b546d7d48e2f5b4c7a8012c37`.
- `logs/shim-probe.log`: SHA-256
  `a905eefc4ca3d0470e536dac0f9aafbc876ffe49bc612287ac4336708a094b09`.
- `logs/compose-down.log`: SHA-256
  `e11d2f8ed6c0ebd4ba3b83e31c05c0640a901a3c9865e7fdd3c1cd5b32ee5154`.

#### Local runtime-dir TDD closure and next-session delta

Commit `3ea9bd90c3b8e26a8f885551629402aa40d52084` completed the local
test-first correction. The focused contract was RED before implementation
because unqualified `tempfile.mkdtemp()` resolved under Windows system temp
instead of `RuntimeConfig.output_dir` (`1 failed in 1.13s`). The implementation
now creates a project-prefixed direct child of the owned output directory and
allows `_remove_runtime_dir()` to delete only that exact resolved parent and
prefix.

Regression coverage proves that shim start, shim probe, and every
pack/observer `:/shim:ro` mount use the same runtime child; token, certificate,
and key material are removed after PASS and forced baseline failure; and a
matching-prefix directory outside the exact output parent is preserved with a
cleanup error. Independent Codex verification observed runtime/foundation
tests `39 passed in 9.94s`; Ruff check/format, `py_compile`, UTF-8/LF/NUL, and
`git diff --check` passed. No SSH, Docker, Compose, or Mac runtime action ran.

Treat every `r1` through `r6` identity, wrapper, and artifact as immutable
evidence. A later fresh `r7` requires separate authorization plus new exact-HEAD
archive, snapshot, project, output, and wrapper identities and fresh protected
co-tenant preflight before any stop. The local unit gate does not prove
Docker/Colima bind visibility or predict rehearsal PASS. Push, traffic, full
soak, Mac rollback, and production gates remain unauthorized or open.

### `r7` one-shot rehearsal — 2026-08-20

The explicitly authorized `r7` slice used exact source commit
`e1e739273146658f8f40fe217e9e1b01ee006714` from fresh shared-root snapshot
`/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-e1e7392-r7`, Compose
project `agentflow-ci-soak-e1e7392-r7`, and output directory
`.artifacts/soak-rehearsal-2000-e1e7392-r7`. The exact-HEAD archive SHA-256 was
`d65b095c5381fb99837ff8109c7e82a88968d9aa51fe49c004a31172835aebd1`.
The critical Git blobs were base Compose `a731a87a`, Flink Compose `838ccf89`,
soak Compose `95f38bc1`, runtime `14492110`, shim `e5cb97f5`, and Iceberg init
`b5f9129a`; the corresponding extracted SHA-256 values matched local HEAD.

`run-rehearsal-e1e7392-r7.sh` differed from the immutable `r6` wrapper only in
the snapshot, output, project, archive filename/hash, and runtime hash. Local
and remote `bash -n` passed, and both copies had SHA-256
`b8973d6125fe82adb2cdbc551e6233ea36fee94a2a11820865bd9eef8a8c3189`.
A read-only bind probe on the exact target Docker socket saw Iceberg init SHA-256
`226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`;
the merged Compose config SHA-256 was
`3269b8172e8a61398be3326b60b25f7df7ba4fa86baa22281df7294b8c176873`.

The first read-only preflight stopped on a five-second host curl timeout to
ClickHouse's VM bridge address `172.18.0.1:8123`. This was a control-probe
transport error, not a co-tenant failure: the exact ClickHouse container was
running, healthy, restart zero, and `clickhouse-client SELECT 1` returned `1`.
Only that probe transport changed; the single permitted full preflight rerun
then passed before any remote resource mutation.

The wrapper invoked the controller exactly once with `--count 2000`; it printed
`PREFLIGHT_RESULT=PASS`, stopped exactly four protected co-tenants, and ended:

```text
RESULT=FAIL reason=shim_probe_failed
CONTROLLER_RC=1
RESTORE_RESULT=PASS
```

The prior runtime-dir correction worked. `shim-start.log` contains one valid
container ID, `7fb70f8e298d709f19f344219c111f5c61c82ea80e973a6c43a266c8a7a019e1`.
The probe could read token and CA material, establish HTTPS, and receive an
HTTP response. Runtime state records 18 failed probe attempts. The per-step log
is overwritten on each attempt, so only the final response is durable; it
contains `urllib.error.HTTPError: HTTP Error 503: Service Unavailable` rather
than the `r6` `/shim/token` `FileNotFoundError`. At collection time the shim was
running, the JobManager was healthy, and the TaskManager was running without a
Docker health object.

The exact first causal failure is proven by the daemon boundary.
`DockerSocketInspector` hardcodes Docker API `v1.41`. The target server reports
API `1.53` and minimum supported API `1.44`; a raw identity-bound `v1.41`
inspect returned HTTP 400 with `client version 1.41 is too old`, while the same
`v1.53` request returned HTTP 200. Replaying the saved JobManager and
TaskManager inspect payloads through the exact shim source returned two Ready
items, proving that the saved identity, state, health, restart, and label
contract itself was valid. The shim converts the rejected inspect into a
fail-closed `/healthz` 503. This is not another bind failure, a Flink readiness
failure, an application/data-correctness result, or a soak result.

Wrapper cleanup reported PASS. The first independent postflight observed a
transient Kind `/livez` HTTP 500 after the kube-apiserver process already
existed. No restart or mutation was applied; the next condition-based check
returned `ok` with exactly one kube-apiserver. The single final full postflight
then passed: r7 containers/networks/volumes `0/0/0`, runtime-dir count zero,
cleanup errors zero, no writer, and all four exact protected co-tenants running
with restart count zero. MinIO, Iceberg REST, ClickHouse `SELECT 1`, Kind
`/livez`, and the one-kube-apiserver gate passed. The original Mac checkout
remained at `ae9fb69` with only its three established untracked paths.

Evidence remains under the `r7` output directory:

- `result-final.txt`: SHA-256
  `ede962f78adfac89a7e965d3944e67e13b8e1b88223a76981c077e15a4481c44`.
- `runtime-state.json`: SHA-256
  `91371b945529d8833ebbaa95452a01376d4ac219889ef95fa56757a78508d650`.
- `logs/shim-start.log`: SHA-256
  `655baf62edf82bb033791e35ff118e72558431c790166c015a4cb134d0b26372`.
- `logs/shim-probe.log`: SHA-256
  `8544c9bd8f75a09aff061e7a33821aa6e6573799b07e60d5da0405cd0ebcb81a`.
- `logs/collect-logs.log`: SHA-256
  `c814a6931df7395b05fb2d0241d21cb2a838b890cd8e5241cb96b0528c1210b5`.
- `logs/compose-down.log`: SHA-256
  `a036a2251ca68fdde123779e1b65376e163342481c7a7677546957686d4761f7`.

#### Next-session resume delta

Treat every `r1` through `r7` snapshot, project, wrapper, and artifact as
immutable evidence; do not rerun or adopt them. The previously proposed narrow
Docker API correction is superseded as the immediate next slice. Do not edit
project code, prepare `r8`, or launch another rehearsal before completing the
read-only architecture audit below.

##### Seven-attempt causal ledger

The seven unsuccessful attempts are not seven workload or soak failures. They
stopped at different control-plane boundaries, and none reached the complete
baseline/observer/producer/verification sequence.

| Attempt | First stopping boundary | Proven cause | Current closure evidence |
| --- | --- | --- | --- |
| `r1` | Wrapper, before Compose | The wrapper selected `/usr/bin/python3` 3.9.6 instead of a supported interpreter; no terminal result file exists. | Later wrappers select `/usr/local/bin/python3` and enforce Python >=3.11. Re-audit interpreter discovery and preflight ownership. |
| `r2` | `iceberg-init` one-shot container | The snapshot was outside the Colima shared root, so the bind existed in the VM without `scripts/init_iceberg.py`; controller result was `one_shot_exit_nonzero`. | Later snapshots use the shared root and an identity-bound bind probe. `r6` proved that checking only static snapshot binds was insufficient. |
| `r3` | Orchestration preflight; controller never ran | The first delegated run hit a headless permission boundary; the cause-specific run exhausted its poll budget after creating only a partial snapshot. There is no durable bind-probe result. | No runtime claim exists. The partial snapshot is evidence-only; audit the launch/delegation boundary separately from controller behavior. |
| `r4` | Compose `up-app` | `serving-bridge` inherited the API image healthcheck for port `8000` although it exposes metrics on `9108`; result was `up_app_failed`. | Service-level health contracts were added for `serving-bridge` and `lake-materializer`; local config/tests passed and `r5` crossed this gate. |
| `r5` | Detached shim identity parsing | Compose 5 progress on stderr was merged with stdout, so a valid container ID embedded in multiline output was rejected as `shim_container_id_invalid`; observer start had the same latent parser. | Commit `d20379e5781b9d6d1fc3a6f609d0c64f368b97e7` separated channels and added one shared exact-line parser; `r6` and `r7` crossed this gate. |
| `r6` | HTTPS shim probe | Runtime token/TLS material was created under macOS `/var/folders/...`, outside the Colima shared root; `/shim` appeared empty and the probe raised `FileNotFoundError`. | Commit `3ea9bd90c3b8e26a8f885551629402aa40d52084` placed material under the owned output directory; `r7` proved token/CA visibility and HTTPS reachability. |
| `r7` | Shim Docker inspect | `DockerSocketInspector` hardcodes API `v1.41`, below the daemon minimum `1.44`; inspect returned HTTP 400 and the shim failed closed with HTTP 503. | Root cause is proven, but the code contract remains open. Do not implement it until the architecture audit identifies all related Docker-socket/version assumptions and required tests. |

##### Mandatory next-session architecture audit

The next named slice is one read-only, end-to-end architecture audit. Start
from the ledger above and trace the complete path:

```text
Windows workspace -> SSH/wrapper -> macOS filesystem -> Colima VM/Docker socket
-> Compose -> runtime controller -> TLS shim -> Docker inspect -> Flink
-> baseline/observer/producer/verify -> cleanup -> protected co-tenant restore
```

The audit must cover, at minimum:

1. Every static and runtime-generated host path, Colima sharing rule, and
   read-only bind, including ownership and cleanup boundaries.
2. Python selection, Docker Engine API negotiation/minimum versions, Docker
   Compose 5 stdout/stderr and one-shot semantics, and exact container identity.
3. Base-image healthcheck inheritance, service overrides, readiness ordering,
   Flink task/checkpoint gates, and observer/shim lifecycle symmetry.
4. Probe correctness and restoration acceptance. Specifically reconcile the
   transient ClickHouse host-route timeout and the gap between kube-apiserver
   process presence, `RESTORE_RESULT=PASS`, and Kind `/livez` readiness.
5. Evidence durability and failure taxonomy. Repeated probe logs are currently
   overwritten and HTTP error bodies are not preserved reliably; distinguish
   wrapper, controller, infrastructure, application, data, and soak failures.
6. Cleanup idempotency, runtime-secret removal, project-resource accounting,
   co-tenant identity/port guards, concurrency exclusion, and failure paths.
7. Existing unit/integration coverage for every `r1`-`r7` cause, plus latent
   variants that can be detected locally without another external rehearsal.

The audit deliverable must contain an architecture diagram, an `r1`-`r7`
traceability matrix (cause -> evidence -> correction -> test -> residual risk),
a severity-ranked defect register, and one consolidated local remediation plan.
It must state which findings are proven and which are hypotheses. No code change
belongs to the audit slice. Do not authorize or predict `r8` until the audit is
complete, all statically detectable harness-contract defects have explicit
dispositions, and a single architecture-readiness gate is defined. Push,
traffic, full soak, Mac rollback, and production gates remain unauthorized or
open.

### r1-r7 architecture audit completion — 2026-08-20

The required read-only audit is complete in
`ci-soak-r1-r7-architecture-audit.md` against baseline
`b151a1f98d0151bc3e84cfa93618fc85d7b78f64`. Its current deterministic verdict
is `ARCHITECTURE_READY=BLOCKED`, with `A-01` through `A-09` as blockers.
`A-10` is an explicitly accepted bounded Docker-socket risk; `A-11` is closed
by marking the older foundation handoff as historical rather than current.

The audit preserves these dispositions: the first causes of `r4`, `r5`, and
`r6` are locally closed and later attempts crossed them; none of `r1`-`r7`
completed the baseline/observer/producer/verification sequence; and every old
snapshot, project, wrapper, and artifact remains immutable evidence. It makes
no application, data-correctness, soak, rollback, production, or external
readiness claim.

The exact next named slice is **L1 / `A-01` only**: local test-first bounded
Docker daemon API-version discovery in `scripts/golden_soak/pods_shim.py` and
`tests/unit/test_ci_soak_runtime.py`. Do not combine `A-02`, prepare `r8`, or
perform SSH/Docker/Compose runtime mutation. A later external attempt still
requires separate authorization, fresh identities, and a locally passing
architecture-readiness gate.

### A-01 local Docker API negotiation closure — 2026-08-20

L1 / `A-01` is `CLOSED-LOCAL`. `DockerSocketInspector` no longer sends an
inspect request through fixed API `v1.41`. It first performs bounded unversioned
`GET /version`, requires valid ordered `ApiVersion` and `MinAPIVersion` values,
selects the highest overlap with the supported `1.41`-`1.53` range, caches that
selection, and uses it for exact identity-bound inspect paths. A missing,
malformed, non-200, oversized, timed-out, or incompatible discovery fails
closed; existing inspect timeout, size, payload, and identity gates remain.

The test-first evidence is explicit: before implementation, 15 new transport
cases failed on the direct `/v1.41` behavior and the pre-I/O invalid-ID guard
passed. After implementation, all 16 focused cases passed. The proportional
aggregate reported `55 passed`; Ruff check, Ruff format check, `py_compile`,
merged Compose `config --quiet`, and diff checks also passed. No Docker daemon,
container, SSH, Mac checkout, `r8` identity, or external state was used.

`ARCHITECTURE_READY` remains `BLOCKED` on `A-02` through `A-09`; `A-10` stays
accepted and `A-11` stays closed. The exact next separate slice is L2 /
`A-02` only. It must preserve bounded retry and HTTP diagnostics locally; it
does not authorize an external rehearsal or reuse of any `r1`-`r7` identity.

### A-02 durable retry and HTTP diagnostics closure — 2026-08-20

L2 / `A-02` is `CLOSED-LOCAL`. Each `shim-probe` and `observer-ready` retry now
writes `logs/<step>.attempt-###.log`, retains the backward-compatible latest
`logs/<step>.log`, and atomically updates `logs/<step>.attempts.json` in strict
attempt order. The summary and `runtime-state.json` record return code, written
bytes, original combined-output bytes and SHA-256, truncation state, and exact
attempt log name. A duplicate or invalid attempt number fails closed.

The container-side probe catches `HTTPError`, records bounded status, body
preview, captured byte count/SHA-256, and completeness before returning nonzero.
The shim records equivalent bounded internal Docker diagnostics to stderr while
its HTTPS response remains the same sanitized reason. Oversized previews and
command logs stay bounded; a truncated command log embeds its original byte
count and SHA-256.

Test-first evidence: all five focused contracts failed before implementation
at the expected missing boundaries, then all five passed. The proportional
aggregate reported `59 passed`; Ruff check/format, `py_compile`, merged Compose
`config --quiet`, and diff checks passed. No Docker daemon, container, SSH, Mac
checkout, `r8` identity, or external state was used.

`ARCHITECTURE_READY` remains `BLOCKED` on `A-03` through `A-09`; `A-10` stays
accepted and `A-11` stays closed. The exact next separate slice is L3 /
`A-06` + `A-09` only: post-down zero-resource proof and exact transient
shim/observer identity symmetry. It does not authorize an external rehearsal.

## Authoritative next-session resume checkpoint — 2026-08-20

This section supersedes earlier next-step statements in this file. It is the
tracked starting point for the next CI-soak session.

### Exact state and evidence

- The latest implementation baseline is
  `c798e716e4de5721ed9e8cbf37747a66c3dd4689`
  (`fix(ops): preserve soak retry diagnostics`). Its immediate local closure
  chain is `6492858` (r1-r7 audit), `12b0320` (L1 / `A-01`), then `c798e71`
  (L2 / `A-02`).
- L1 and L2 are `CLOSED-LOCAL`. The last proportional implementation gate
  reported `59 passed`; Ruff check and format, `py_compile`, merged Compose
  `config --quiet`, UTF-8/LF/NUL, and diff checks passed.
- `ARCHITECTURE_READY=BLOCKED`. The remaining blockers are exactly `A-03`
  through `A-09`; `A-10` is accepted and `A-11` is closed.
- The corrected API-negotiation and diagnostic paths are locally proven only.
  No Docker daemon, container, SSH, macOS checkout, `r8`, traffic, soak,
  rollback, production action, or push was used or authorized.
- At this handoff, the tracked implementation and index were clean. Existing
  untracked paths are protected user artifacts: refresh status and never use a
  bulk staging command.

### Start here

1. Run `git status --short --branch` and `git log -4 --oneline`; treat the
   current HEAD plus the implementation baseline above as authoritative.
2. Read the `A-06` and `A-09` register rows and L3 plan in
   `ci-soak-r1-r7-architecture-audit.md`. Do not reopen L1 or L2 without new
   failing evidence.
3. Confirm `scripts/golden_soak/runtime.py` and
   `tests/unit/test_ci_soak_runtime.py` have no unrelated changes before
   editing.
4. Implement one test-first slice only: **L3 / `A-06` + `A-09`**. Run focused
   RED fixtures first, make the smallest runtime change, then run one
   proportional aggregate gate and commit only the scoped files.

### L3 acceptance contract

1. After a successful Compose down, exact project-label queries for
   containers, networks, and volumes must all return zero. A query failure or
   any residual resource produces terminal `cleanup_failed`, never PASS.
2. Each detached shim and observer ID must be inspected after start and bound
   to the expected immutable ID, Compose project/service labels, one-off name,
   running state, and restart state. Wrong, exited, restarted, or replaced
   identities fail closed.
3. Terminal cleanup evidence must name those same IDs and prove they were
   removed without replacement; the result must remain available in durable
   runtime evidence.
4. Keep the golden source pack unchanged. Do not combine `A-03`, perform any
   external rehearsal, reuse `r1`-`r7` identities, or push.

## Authoritative next-session resume checkpoint — L3 closed; L4 next

This section supersedes the earlier checkpoint above. It is the tracked
starting point for the next CI-soak session.

### L3 outcome and evidence

- Implementation baseline:
  `012bcb46c95e48d8619ac50905410362d73cb8e8`
  (`fix(ops): bind soak transient cleanup evidence`). L1 / `A-01`, L2 /
  `A-02`, and L3 / `A-06` + `A-09` are `CLOSED-LOCAL`.
- Detached shim and observer IDs are remembered before inspection, then bound
  to the exact ID, Compose project/service/one-off labels, custom name,
  running state, and zero restarts before the lifecycle advances.
- Cleanup removes those exact remembered IDs, records same-name absence, runs
  Compose down, and performs separate exact project-label queries for
  containers, networks, and volumes. Query failure, residue, replacement, or
  missing proof is terminal `cleanup_failed`.
- Durable `runtime-state.json` records both transient identities and all three
  cleanup-accounting results; bounded step logs retain the corresponding
  command evidence.
- Test-first RED was `29 failed, 51 deselected`. Focused GREEN was `29 passed,
  51 deselected`; the independent proportional gate reported `88 passed in
  31.21s`. Ruff check/format, `py_compile`, merged Compose `config --quiet`,
  UTF-8/LF/NUL, eight protected pack hashes, and diff checks all passed.
- Grok route transparency: `local_grok_cli`, requested model `grok-4.6`, run
  ID `de-ci-soak-l3-identity-cleanup-20260820-grok01`. It left only the RED
  test WIP before the bounded 10-minute run ended with no stdout/stderr;
  Codex cancelled the single writer, completed the production patch, and
  independently verified it. No writer remains.
- The golden source pack is byte-identical. No Docker daemon/container, SSH,
  macOS checkout, `r8`, traffic, soak, rollback, production action, push, or
  protected untracked path changed.

`ARCHITECTURE_READY=BLOCKED` remains on `A-03` through `A-05`, `A-07`, and
`A-08`. The corrected L1-L3 paths are locally proven only.

### Start here

1. Refresh `git status --short --branch` and `git log -4 --oneline`. Preserve
   every established untracked path and never bulk-stage.
2. Read the `A-03` register row and L4 plan in
   `ci-soak-r1-r7-architecture-audit.md`. Do not reopen L1-L3 without fresh
   failing evidence.
3. Implement one separate test-first slice only: **L4 / `A-03`**. Introduce
   the smallest tracked POSIX bootstrap plus a testable Python wrapper under
   `scripts/golden_soak/`, with focused coverage in
   `tests/unit/test_ci_soak_wrapper.py`.
4. Pin supported-interpreter discovery, `NOT_INVOKED` versus controller
   failure, primary/restore result precedence, and exactly one terminal
   wrapper result. Stop after local verification and a scoped commit.

L4 remains local-only. Do not combine path/restore/lock findings, launch an
external rehearsal, prepare `r8`, reuse any `r1`-`r7` identity, or push.

## Authoritative next-session resume checkpoint — L4 closed; L5 next

This section supersedes every earlier checkpoint above. It is the tracked
starting point for the next CI-soak session.

### L4 outcome and evidence

- Implementation baseline:
  `2393495de842717f947da136e0c9c98a04771de0`
  (`fix(ops): add soak wrapper terminal taxonomy`). L1 through L4 are
  `CLOSED-LOCAL` for `A-01`, `A-02`, `A-03`, `A-06`, and `A-09`.
- `scripts/golden_soak/bootstrap.sh` is an executable POSIX entry point. It
  checks newline-delimited candidates in order, requires Python >=3.11, and
  emits a durable `WRAPPER_FAILURE`/`NOT_INVOKED` result if none is supported.
  If the wrapper does not emit a terminal record, bootstrap persists the
  distinct `ORCHESTRATION_STOP` outcome.
- `scripts/golden_soak/wrapper.py` reads a bounded JSON command plan, invokes
  controller and restore commands without a shell, and writes plus prints one
  canonical JSON record. A zero controller RC without a valid controller PASS
  record fails closed. Restore failure overrides a candidate PASS while the
  exact primary result and both RC dimensions remain present.
- Test-first RED was `7 failed` at the two missing implementation files. The
  final focused suite reported `9 passed`; the proportional runtime,
  foundation, and wrapper aggregate reported `97 passed in 26.33s`. Ruff
  check/format, `py_compile`, Git Bash `bash -n`, UTF-8/LF/NUL, protected pack
  hashes, exact changed paths, executable mode, and diff checks passed.
- The bounded plan-file transport replaced opaque JSON argv after one focused
  diagnostic proved MSYS altered embedded quoting at the shell/native-Python
  boundary. No diagnostic output remains in tracked code.
- Grok was optional for this slice and was not used. The previous bounded Grok
  route had produced no terminal output; this local fixture-only slice was
  implemented and independently verified by Codex.
- The golden source pack is byte-identical. No Docker daemon/container, SSH,
  macOS checkout, `r8`, traffic, soak, rollback, production action, push, or
  protected untracked path changed.

`ARCHITECTURE_READY=BLOCKED` remains on `A-04`, `A-05`, `A-07`, and `A-08`.
The corrected L1-L4 paths are locally proven only.

### Start here

1. Refresh `git status --short --branch` and `git log -4 --oneline`. Preserve
   every established untracked path and never bulk-stage.
2. Read the `A-04`, `A-05`, `A-07`, and `A-08` register rows and L5 plan in
   `ci-soak-r1-r7-architecture-audit.md`. Do not reopen L1-L4 without fresh
   failing evidence.
3. Implement one separate test-first slice only: **L5 / `A-04` + `A-05` +
   `A-07` + `A-08`**. Extend the tracked wrapper with the declared path,
   probe-viewpoint, restore-readiness, and exclusive-lock contracts using fake
   command transitions only.
4. Keep L5 local. Do not launch an external rehearsal, prepare `r8`, reuse any
   `r1`-`r7` identity, change the golden pack, or push.

## Authoritative next-session resume checkpoint — L5 closed; L6 next

This section supersedes every earlier checkpoint above. It is the tracked
starting point for the next CI-soak session.

### L5 outcome and evidence

- Implementation baseline:
  `59e1f7e3ebd59d1c6db6295e8d1e42baf797b567`
  (`fix(ops): enforce soak rehearsal preflight contract`). L1 through L5 are
  `CLOSED-LOCAL` for findings `A-01` through `A-09`.
- The CLI now accepts only bounded schema-2 plans. Snapshot, output parent,
  controller result, and wrapper result are tied to an absolute shared-root
  contract. Separate source/output daemon probes require exact SHA-256 values,
  then exact cleanup evidence, before the stop boundary.
- ClickHouse container health, macOS host route, and Kind/workload route are
  named ordered checks with distinct diagnostic classifications. All three run
  exactly once per preflight; a failure blocks stop without raw retry.
- An atomic owner-directory lock is acquired before preflight and held through
  final restoration. Owner metadata binds attempt, PID, time, and token. Valid
  ownership is busy; malformed/missing stale state fails closed and is never
  auto-broken. The two-process fixture proves only one owner reaches stop.
- Restoration requires the exact Kind container ID, `running`, zero restarts,
  exactly one kube-apiserver, and at least two consecutive bounded
  `/livez=ok` observations. `500/ok` cannot pass; `500/ok/ok` passes only on
  the final transition.
- Test-first RED introduced 10 L5 failures; the two-process fixture received
  one escaping correction and was re-confirmed at the missing owner-lock
  boundary. Final focused verification is `19 passed`. The independent
  runtime/foundation/wrapper aggregate reported `107 passed in 27.79s`.
  After the single Ruff follow-up, Ruff check/format, `py_compile`, the focused
  19 tests, and `git diff --check` passed. Git Bash `bash -n`, merged Compose
  `config --quiet`, UTF-8/LF/NUL, eight protected pack hashes, and the exact
  changed-path allowlist also passed.
- Grok was optional and was not used. No Docker daemon/container, SSH, macOS
  checkout, `r8`, traffic, soak, rollback, production action, push, or
  protected untracked path changed. The golden source pack remains
  byte-identical.

All finding contracts `A-01` through `A-09` are closed locally. The current
verdict remains `ARCHITECTURE_READY=BLOCKED` only because the separate L6
executable one-line gate and final documentation closure do not yet exist. All
corrected runtime paths remain `EXTERNAL-UNVERIFIED`.

### Start here

1. Refresh `git status --short --branch` and `git log -4 --oneline`. Preserve
   every established untracked path and never bulk-stage.
2. Read section 8 of `ci-soak-r1-r7-architecture-audit.md`. Do not reopen
   L1-L5 without fresh failing evidence.
3. Implement one separate local slice only: **L6 — executable architecture
   gate and documentation closure**. The gate must evaluate the documented
   checks and print exactly one
   `ARCHITECTURE_READY=PASS|BLOCKED blockers=... head=...` line.
4. Keep L6 local. Do not launch an external rehearsal, prepare `r8`, reuse any
   `r1`-`r7` identity, change the golden pack, or push.

## Authoritative next-session resume checkpoint — L6 closed; local gate PASS

This section supersedes every earlier checkpoint above. It is the tracked
starting point for any later CI-soak decision.

### Evidence and HEAD map

Keep these identities separate:

| Identity | Exact value | Authority |
| --- | --- | --- |
| Gate feature commit | `44fc1a1f2ad64abc856a231545beb852a650a0c8` | Introduced the L6 entry point and tests. |
| Gate evidence HEAD | `809978b4e7e20b47fab19dbe91495b464a672a05` | Exact clean HEAD on which the complete gate emitted PASS. |
| First docs closure | `bfb6b442d7cec4c5ce5fbd08c38289e0720ff6ec` | Docs-only closure after the PASS; no complete gate execution occurred at this HEAD. |
| Current checkout | Resolve with `git rev-parse HEAD` and confirm with `git status --short --branch`. | Do not describe it as gate-tested unless a terminal verdict names the same exact HEAD. |

The PASS below is therefore exact historical execution evidence for
`809978b4...`, while `bfb6b44...` and later documentation-only commits preserve
and clarify that evidence. They do not silently move the executed verdict to a
new HEAD.

### L6 outcome and evidence

- Gate implementation commits:
  `44fc1a1f2ad64abc856a231545beb852a650a0c8`
  (`feat(ops): add CI soak architecture gate`) and
  `809978b4e7e20b47fab19dbe91495b464a672a05`
  (`fix(ops): scope soak gate format check`). L1 through L6 are complete
  locally.
- `scripts/golden_soak/architecture_gate.py` checks the finding register,
  focused runtime/foundation/wrapper tests, Ruff lint and L6 changed-path
  formatting, `py_compile`, merged Compose configuration, Git diff/clean
  state, eight protected pack hashes, UTF-8/LF/NUL, and exact HEAD. It
  suppresses every child command and emits one terminal line.
- RED was `7 failed` at the missing entry-point boundary. Focused GREEN is
  `7 passed`; Ruff check/format, `py_compile`, encoding, and diff checks passed.
- The first clean-HEAD gate execution correctly failed closed with
  `G-RUFF`: lint was green, while the historical unchanged foundation fixture
  did not match the current formatter. The single QA follow-up pinned
  changed-path formatting to the two L6 Python files without rewriting that
  unrelated fixture. The one permitted full re-run emitted exactly:

  ```text
  ARCHITECTURE_READY=PASS blockers=0 head=809978b4e7e20b47fab19dbe91495b464a672a05
  ```

- Grok was optional and was not used. No Docker daemon/container, SSH, macOS
  checkout, external rehearsal, `r8`, traffic, soak, rollback, production
  action, push, or protected source-pack/untracked mutation occurred.

The last executed local verdict is `ARCHITECTURE_READY=PASS` at `809978b4...`;
blockers were zero. This is not runtime evidence and does not authorize any
external action. All corrected runtime paths remain `EXTERNAL-UNVERIFIED`.

### Exact next-session resume

1. Run only the read-only orientation commands first:

   ```powershell
   git status --short --branch
   git log -4 --oneline
   git rev-parse HEAD
   ```

2. Read the first block in `AGENT_STATE.md`, this final harness checkpoint,
   then sections 8 and 9 of `ci-soak-r1-r7-architecture-audit.md`. Earlier
   checkpoints in this file are chronology, not current instructions.
3. Expect no active writer and a clean tracked tree/index. Preserve all
   untracked paths shown by `git status`; the current protected list is copied
   into the first `AGENT_STATE.md` block. Never bulk-stage them.
4. Without fresh explicit authorization for an external preflight, there is no
   open CI-soak implementation or runtime action. Do not create `r8`, start
   Docker/Colima, use SSH, launch traffic/soak/rollback, or push.
5. If that external authorization is later given, first execute the local gate
   once from a clean current checkout and require PASS at that exact HEAD.
   Then create a new exact-HEAD archive plus fresh shared-root
   snapshot/project/output/wrapper identities, acquire the owner lock, and
   complete every read-only pre-stop probe. Never reuse `r1`-`r7`.

Grok was optional and was not used for L6 or this handoff. All corrected
external paths remain `EXTERNAL-UNVERIFIED`.

## Authoritative next-session resume checkpoint — r8 preflight failed at host route

This section supersedes every earlier checkpoint above. It records only the
explicitly authorized external preflight; no rehearsal or controller ran.

### Exact identity and local gate

- Source and exact gate HEAD:
  `f88ff4f6cf68c3af859ff1a5a2bd329e5cb4fa12`.
- Local terminal evidence:
  `ARCHITECTURE_READY=PASS blockers=0 head=f88ff4f6cf68c3af859ff1a5a2bd329e5cb4fa12`.
- Fresh snapshot:
  `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-f88ff4f-r8`.
- Reserved project and output: `agentflow-ci-soak-f88ff4f-r8` and
  `.artifacts/soak-rehearsal-2000-f88ff4f-r8` under that snapshot.
- Exact-HEAD archive SHA-256:
  `e039969cc336baa8c50bd708cb14668483e353a2e5187a7c35e004a0df010c28`.
- Preflight-wrapper SHA-256:
  `41fe8d09b9a0018d9048edabeb7532c6dbebb22094e5541fad3823a13e010919`.

The local and transferred archive hashes matched. WSL and native macOS Bash
syntax checks passed for the wrapper. The wrapper was preflight-only: it had no
stop or controller path and held one exclusive owner lock through its checks.

### Terminal preflight evidence

The exact durable result is:

```text
PREFLIGHT_RESULT=FAIL
REASON=clickhouse_host_route_failed
SOURCE_HEAD=f88ff4f6cf68c3af859ff1a5a2bd329e5cb4fa12
DOCKER_API=1.53
DOCKER_MIN_API=1.44
PROJECT_RESOURCES=0/0/0
OWNER_LOCK_RELEASE=PASS
STOP_COMMAND=NOT_INVOKED
CONTROLLER=NOT_INVOKED
```

The source daemon-visibility probe returned the exact `init_iceberg.py` hash
`226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`.
The distinct output-path probe returned
`2b86e90acec6967a4be47aae72888e2d5c9bf70cce2f5bd6d0faac5389bee7a3`,
and both disposable probe identities were absent afterward. Merged Compose
validation passed; the captured configuration hash is
`2e03cbc07262f8ebb1e047b6f6faddf527db1b20016db657f6bef20633c36ea1`.

All three ClickHouse viewpoints ran exactly once:

```text
container_health_rc=0 output=healthy
host_route_rc=28 output=
workload_route_rc=0 output=1
```

| Viewpoint | RC / output | Result |
| --- | --- | --- |
| Exact container health | `0 / healthy` | PASS |
| macOS host route | `28 / empty`; timeout after `5002` ms | FAIL |
| Kind/workload route | `0 / 1` | PASS |

This is a host-route transport failure, not a ClickHouse service failure or a
workload-route failure. The preflight failed closed before any co-tenant stop.

### Independent postflight and boundary

- Owner lock, candidate writer, two probe containers, and project-labeled
  containers/networks/volumes were absent.
- The four exact protected container IDs were still `running` with restart
  count `0`. MinIO and ClickHouse health had passed before the host-route gate.
- The original Mac checkout remained at `ae9fb69` with exactly its three
  established untracked paths.
- Grok was not used. No rehearsal, controller, traffic, soak, rollback,
  production action, fetch, push, or existing-checkout mutation occurred.

Treat every `f88ff4f-r8` path and identity as immutable failure evidence. Do
not raw-retry the host probe, launch the controller, or adopt this identity for
a rehearsal. A later external diagnostic requires fresh explicit authorization
and a distinct named slice with a narrowed host-route hypothesis. The local
`.codex-runtime/` transfer staging remains untracked because cleanup was
rejected before execution; never bulk-stage it.

## Read-only macOS host-route diagnosis - 2026-08-21

Freshly authorized diagnostic identity `mac-host-route-diag-20260821-01`
narrowed the r8 host-route failure without repeating its HTTP probe. The exact
protected ClickHouse container remained `running`, `healthy`, restart count
`0`. Its Docker metadata reports
`8123/tcp -> 172.18.0.1:8123`; the address is a bind inside the active Colima
VM, not a forwarded macOS endpoint.

The macOS route to `172.18.0.1` uses the default gateway `192.168.1.1` on
`en1`. No host TCP listener exists on `8123`, and a distinct bounded loopback
probe to `127.0.0.1:8123` failed immediately with curl `7`. In the working
comparison, the exact Kind API binding is `127.0.0.1:50145` and the Colima SSH
forwarder owns that macOS listener. Effective Colima settings are
`network.address=false`, `network.hostAddresses=false`, and
`portForwarder=ssh`.

The container labels identify its source as deleted temporary file
`/tmp/agentflow-chk-restore-rv-20260802-01/clickhouse-compose.yml`. By
contrast, both tracked Compose definitions in unchanged Mac checkout
`ae9fb69...` use `127.0.0.1:8123:8123`. The default `colima-nsa` Docker
context currently points to an absent socket, but the r8 wrapper pinned the
live `agentflow-fc5-7113966` socket, so that separate shell drift did not cause
r8.

This confirms external runtime binding drift. It does not justify a local code
change or weakening the three-viewpoint gate. No external state changed. A
future remedy must be separately authorized, preserve the protected evidence,
define rollback, and use new runtime and preflight identities; r8 remains
immutable.

## ClickHouse dual-route rebind - 2026-08-21

Explicitly authorized slice `mac-clickhouse-loopback-rebind-20260821-01`
replaced the active ClickHouse runtime configuration without deleting its data
volume or rollback source. Control script SHA-256 was
`158abc6cb1725e311a969c1af0acea1527e133772ea88b41af34ada9c825bde2`;
candidate Compose SHA-256 was
`a5ab84cc9af25da5c4c3ab8c007a547d33df0132820e646737eec979ff46a098`.
Local/remote hashes, macOS `bash -n`, and merged Compose validation matched
before the first mutation.

The new exact ID is
`f0f0b82817bb87ec522f16426795df021e8d249fdc0c07a9474ac34717488c61`.
It uses image ID
`sha256:1ffa82edee000a42c09313bd9f1293d94c570aee74babc1b3ca9983a35fa597b`,
the existing `agentflow-ch-rv-20260802-01-data` volume, and the existing Docker
network at `172.20.0.2`. It is `running`, `healthy`, restart `0`.

Exact terminal checks passed:

```text
RESULT=PASS
REASON=dual_route_rebind_verified
CONTAINER_ROUTE=PASS
HOST_ROUTE=PASS
WORKLOAD_ROUTE=PASS
ROLLBACK=READY_SOURCE_STOPPED
```

Docker publishes both `127.0.0.1:8123` and `172.18.0.1:8123`. In-container
`clickhouse-client`, macOS-host curl, and exact Kind-container curl each
returned `1`. The pre/post `agentflow` aggregate matched exactly at `5` tables
and `5,546,151` total rows. Both evidence files have SHA-256
`753b2d3cdb245c3175b29925ec025544f300bee79eab66a8da34b84877cab2aa`;
the terminal result hash is
`dd764aa43cf15ad946bd958bd66a9a0cc7c54d1bf370b7b6e5129022a1e8904b`.

Old exact ID `a8cc630e...` stopped cleanly with exit `0`, is disconnected from
the network, and remains available for rollback. Docker copied the volume tree
to the fresh evidence directory (`3,564,864 KiB` allocated versus
`3,515,788 KiB` at source). The allocation difference is expected across
filesystems and is not a byte-identity claim.

Independent postflight found all other protected IDs running with restart `0`,
MinIO healthy, Kind `/livez=ok`, no owner lock, and no writer. The Mac checkout
was unchanged. No preflight, controller, rehearsal, traffic, soak, rollback
execution, production action, fetch, or push occurred. Deleting the stopped
source or backup, executing rollback, or starting a fresh preflight each
requires separate authorization; r8 stays immutable.

## Exact-HEAD r9 preflight PASS - 2026-08-21

Authorized slice `ci-soak-7e8ec87-r9-preflight` used exact source and gate HEAD
`7e8ec87c25bbdc8f8aa58c116ded9914470789cb`. The complete local gate returned
`ARCHITECTURE_READY=PASS blockers=0` at that HEAD. Fresh immutable identities
were:

| Identity | Exact value |
| --- | --- |
| Snapshot | `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-7e8ec87-r9` |
| Reserved project | `agentflow-ci-soak-7e8ec87-r9` |
| Reserved output | `.artifacts/soak-rehearsal-2000-7e8ec87-r9` under the snapshot |
| Archive SHA-256 | `f52f4587f8db5a2d53876caf0c847c6a8093edff9da0b46f1d3d2d42e43df1a1` |
| Final preflight wrapper SHA-256 | `0bc8edda7a2e933a690c32bb3956353668e417cfea396301c163f30daca0a68e` |

The first invocation failed closed immediately with
`reason=archive_missing`: the copied wrapper still named the r8 archive
basename while the transferred file used the r9 basename. This happened
before archive extraction, preflight-evidence/output creation, Docker access,
owner-lock acquisition, or probe creation. One exact-line correction changed
only that basename. Local and native macOS `bash -n`, transfer hashes, absence
of all r9 runtime identities, and the final wrapper hash passed before the
single allowed rerun.

The corrected terminal record is `PREFLIGHT_RESULT=PASS`, `REASON=none`,
Docker API range `1.44..1.53`, and:

```text
container_health_rc=0 output=healthy
host_route_rc=0 output=1
workload_route_rc=0 output=1
STOP_COMMAND=NOT_INVOKED
CONTROLLER=NOT_INVOKED
```

The source and output daemon-visibility hashes were
`226dc8301870ff837028c444c2f690c07c9181d233a8c6fa57635de24eaabada`
and `af34ca8c6da93868be88acb9fc89ecc689e076822886d6a8b4057aadf27db3f6`.
Merged Compose SHA-256 was
`a61188607a1af588e9cc2c0b75ab95ddc66f83d201467e3e1b050b970f43b362`.
The terminal result, ClickHouse probes, and protected-inspect SHA-256 values
were respectively
`418dd88897b9e8d3deb067f796519ec889f7822370f68276071d4c4dfb882d83`,
`0962b7a59839330576e5aefe2c79ef1b69a238271be9d21b0cb4c7604dc71171`,
and `e006049c405f32e07d0d118eb9040ebfe2cff3ce4e58b7c4ae52320a2ae6f42f`.

Independent postflight found candidate project resources `0/0/0`, both probe
containers absent, the output directory empty, and the owner lock absent.
The four exact running protected IDs retained restart count `0`; new
ClickHouse remained `running`, and old exact ID `a8cc630e...` remained
`exited(0)`, restart `0`, disconnected. The Mac checkout remained at
`ae9fb69...` with exactly its established three untracked paths.

This is a successful read-only preflight, not a rehearsal, soak, rollback, or
production result. Preserve the r9 snapshot and evidence. Starting a
controller, stopping co-tenants, creating traffic, or using the reserved
project/output for a rehearsal requires fresh explicit authorization. Grok
was not used; no fetch or push occurred.

## Exact-HEAD r9 rehearsal FAIL — 2026-08-21

Authorized attempt `ci-soak-7e8ec87-r9-rehearsal-20260821-01` consumed the
verified r9 snapshot, project, and output with exactly one controller
invocation at `--count 2000`. All guarded path, source/output visibility, and
three-viewpoint ClickHouse prechecks passed. The four exact protected
co-tenants were stopped and later restored by the guarded wrapper.

The producer returned PASS with `2000/2000` delivered, zero failures,
`21.182s` elapsed, and `94.418541` delivered eps. Verification then failed
closed at the enforced `dual_mean_90` boundary:

```text
RESULT=FAIL reason=verify_failed
result=FAIL reason=catchup_rate_floor
ch_pipeline_phys=291 ch_pipeline_uniq=291
ch_orders_phys=291 ch_orders_uniq=291 expected=2000
```

The count-specific deadline was producer start plus `22.222s`; the observed
producer end left `1.040s`. `verify.log` was created roughly `4.2s` after that
deadline because the verifier is launched as a new Compose one-off container
after producer completion. Even an exact first query at that time could not
prove a `90 eps` applied mean. The observed first query was additionally only
`291/2000` at both ClickHouse surfaces. This is a local orchestration/coverage
gap exposed by the external run, not evidence that the rehearsal passed and
not a reason to weaken the rate floor.

The failure class is not new. The 2026-08-07 FIX2 diagnostic already proved
that creating the verifier after a 2,000-event producer misses the same
count-dependent deadline, and the later FIX4 product contract assigned short
Kind validation to `kind_residual_20` while keeping `dual_mean_90` as the
full-soak acceptance SLA. The CI-soak harness omitted both the historical
verify-before-producer orchestration rule and an explicit phase-specific rate
contract; its mocked success path does not exercise real verifier launch time.

The wrapper terminal record reports `stop_rc=0`, controller invoked with rc
`1`, `restore_rc=0`, `restore_result=PASS`, and `lock_result=RELEASED`.
Independent postflight found candidate project resources `0/0/0`, no writer
or owner lock, and the four protected exact IDs running with restart count
`0`; old ClickHouse `a8cc630e...` remained exited cleanly and disconnected.
The Mac checkout stayed at `ae9fb69...` with its established three untracked
paths.

Terminal SHA-256 values are `91d7345c75f5d145570c9c4e5c5e716a6c5dc26d8a5859738fdf3964fbb3acef`
for `wrapper-result.json`,
`d1083df031a21f392f08e56ed29bbba03078fe1c31e3c5d8767de0ba31524564`
for `result-final.txt`, and
`b73ca3b81a529d4fffb615068a025c81b81e9827fab88570235cc5bd8cd7da17`
for `runtime-state.json`.

The r9 runtime identity is consumed immutable failure evidence. Do not rerun
it. A later attempt requires a separate local TDD contract-reconciliation
slice, a new exact-HEAD gate, fresh identities and preflight, and fresh
external authorization. That slice must preserve the historical short-run
versus full-soak claim boundary or explicitly co-schedule a deliberately
dual-mean rehearsal; it must not lower the full-soak floor. No full soak,
rollback, cleanup, production action, fetch, or push occurred.

## Local r9 contract reconciliation — 2026-08-21

The separate local slice after the retained r9 failure restores the published
FIX4 phase boundary without weakening the full-soak floor. Counts below
`1_440_000` now run `VERIFY_PHASE=canary` with
`AGENTFLOW_RATE_CONTRACT=kind_residual_20`; the exact full count retains
`VERIFY_PHASE=soak` and `dual_mean_90`. The selected phase and contract are
also recorded in `runtime-state.json` and revalidated against the phase-specific
atomic verifier file.

The controller now starts a named detached verifier before producer traffic.
`verify_coschedule.py` emits a readiness marker, waits fail-closed for stable
producer-final evidence or `ABORT`, and then replaces itself with the
byte-pinned `pack/verify.py`. The controller binds the initial verifier by
full container ID, Compose project/service/one-off labels, name, running state,
and zero restarts; after producer completion it waits and logs the same ID,
requires its exact terminal exit state, and removes that exact identity with a
no-replacement proof during cleanup.

TDD RED was two failures: the phase resolver was absent and the ordered path
had no pre-producer verifier start. The focused runtime gate is GREEN at `95
passed`. No Docker, Mac, traffic, rehearsal, soak, rollback, production action,
fetch, or push ran in this local correction.

This is `CLOSED-LOCAL`, not new runtime acceptance. The consumed r9 evidence
remains immutable and failed. Any external validation of this correction needs
a new exact-HEAD architecture gate, fresh snapshot/project/output identities,
fresh preflight, and fresh authorization.

## r10 orchestration stop before mutation — 2026-08-21

The newly authorized post-fix r10 slice passed the complete local architecture
gate at exact HEAD `1fc959efcc1c871fd3057f27a8aef60db44fc878` and created a
local exact source archive only. A bounded `local_grok_cli` run with pinned
requested model `grok-4.6` remained active through all six permitted polls but
emitted no stdout or stderr. It was cancelled once at the monitoring limit;
no duplicate or QA run followed.

Independent byte-exact read-only Mac postflight proved the remote r10
snapshot, control directory, output, preflight evidence, owner lock,
controller, project resources, and probe containers were all absent. The four
protected exact IDs remained running with restart count zero; health/API,
dual-route ClickHouse, Kind `/livez`, and one-kube-apiserver checks passed. The
rollback ClickHouse and original Mac checkout remained unchanged. Therefore
the classification is `ORCHESTRATION_STOP_BEFORE_MUTATION`, with both
`STOP_COMMAND` and `CONTROLLER` `NOT_INVOKED`; there is no r10 rehearsal
verdict.

Canonical evidence is
`ci-soak-r10-orchestration-stop-20260821-01.md`. Treat the r10 prompt, local
control identity, attempt name, and authorization as consumed. A later
external attempt must use fresh r11-or-later identities, a new exact-HEAD gate
and preflight, and fresh authorization. Full soak, rollback, retained-evidence
cleanup, production action, fetch, and push remain unauthorized.
