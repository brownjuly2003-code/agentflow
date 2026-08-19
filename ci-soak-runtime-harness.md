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
