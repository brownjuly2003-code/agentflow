# CI-soak architecture gate (L6)

## Goal

Add one deterministic local entry point that executes the documented
architecture checks and emits exactly one terminal verdict line.

## Tasks

- [x] Add RED fixtures for PASS, fail-closed blockers, exact HEAD, and one-line output.
- [x] Implement bounded audit, command, pack, encoding, and clean-tree checks.
- [x] Run focused tests and static verification, then create a scoped code commit.
- [x] Run the executable gate once on the clean implementation commit.
- [x] Record the result in current audit/handoff documentation.

## Done when

- [x] The gate emits `ARCHITECTURE_READY=PASS blockers=0 head=<exact-head>` only when every documented local check passes.
- [x] Any failed or malformed check emits one deterministic `BLOCKED` line and exits nonzero.
- [x] External rehearsal, Docker runtime, SSH, push, and protected source-pack mutation remain out of scope.
