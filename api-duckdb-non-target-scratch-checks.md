# API DuckDB non-target scratch checks

## Goal

Implement all seven real scratch-only capability probes behind the existing
guard without running SSH or touching the target Pod, volume, or DuckDB bytes.

## Tasks

- [x] Add RED tests for exact per-check evidence, branch-ineligible output,
      process cleanup, and prohibited-target boundaries.
- [x] Implement timing, pause/resume, watchdog, descriptor, metadata,
      same-directory rename, and file/directory sync probes in the guarded
      remote payload.
- [x] Run focused pytest, Ruff, compile, and default non-executing CLI checks.
- [x] Record the verified local implementation in the canonical design and
      durable handoffs; commit only explicit scoped paths.

## Done When

- [x] The remote result schema accepts only all seven bounded scratch results
      plus evidence while keeping I04/I05/I09 false and both branches
      ineligible.
- [x] No `--execute`, SSH, runtime mutation, target access, or push occurs.
