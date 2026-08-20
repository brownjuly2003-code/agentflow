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
