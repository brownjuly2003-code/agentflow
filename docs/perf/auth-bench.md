# Authentication legacy-path benchmark artifact lifecycle

This page owns the runtime artifact produced by the authentication
microbenchmark. The authentication phase reproduces the explicit legacy bcrypt
O(n) lookup that motivated the 2026-06-05 Argon2id plus deterministic
`key_lookup` change. It does not measure the current O(1) candidate-selection
path. The rate-window phase still mirrors the current list-trim implementation.

The immutable laptop measurement that informed M-C4 and closed M-C5 remains at
[`auth-bench-2026-05-26.md`](auth-bench-2026-05-26.md). Preserve that record
byte-for-byte; a new run does not revise or supersede its historical numbers.

## Owner and runtime output

Owning command: `python scripts/perf/auth_bench.py`.

Run the host- and time-dependent workload on `deproject-mac` from an isolated
checkout with the project environment available. It needs no Docker, WSL, or
service stack:

```bash
PYTHONPATH="$PWD/src" python scripts/perf/auth_bench.py
```

The command prints its progress and writes the ignored, replaceable runtime
artifact `.artifacts/perf/auth-bench-current.md`. It validates the output path
before bcrypt setup and refuses to overwrite this lifecycle page or the
immutable 2026-05-26 record.

The report is a single-host microbenchmark, not a served-API or concurrent-load
test, a current production-path measurement, a production SLA, or production
acceptance.

## Promotion boundary

Promote a reviewed result only under a new date-stamped evidence identity with
the exact source commit, host and power profile, Python and dependency versions,
full command and benchmark configuration, sample counts, interpretation
boundary, and runtime-report SHA-256. Update the evidence index and any numeric
current-status claim in the same scoped change. A fresh local artifact does not
supersede the immutable 2026-05-26 record by itself.
