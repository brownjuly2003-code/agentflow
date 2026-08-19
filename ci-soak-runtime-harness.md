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

The next separate slice should extract the same source commit into a fresh
directory below `/Users/julia/agentflow-fc5-7113966`, prove bind visibility
before stopping co-tenants, and then perform at most one new rehearsal. This
failure does not close the Mac Kind operator, HA, Helm rollback, soak, traffic,
or production gates.
