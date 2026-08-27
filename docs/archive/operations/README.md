# Archived operational variants

This directory preserves consumed execution contracts that are no longer safe
operator entrypoints. Use the
[current non-target scratch rehearsal](../../operations/api-duckdb-non-target-scratch-rehearsal-runbook.md)
to prepare any later identity. An archived command, path, or run ID must never
be reused.

## API DuckDB scratch rehearsals

| Variant | Recorded boundary | Why it is archived |
| --- | --- | --- |
| [E22](api-duckdb-non-target-scratch-rehearsal-e22-2026-08-11.md) | `CONSUMED_TRANSPORT_BLOCKED` | Windows text transport failed before probe execution |
| [E24](api-duckdb-non-target-scratch-rehearsal-e24-2026-08-11.md) | `CONSUMED_SCRATCH_REHEARSAL_BLOCKED` | Five checks passed; two compatibility checks were blocked |
| [E26](api-duckdb-non-target-scratch-rehearsal-e26-2026-08-11.md) | Executed once; `SCRATCH_REHEARSAL_BLOCKED` | Six checks passed; metadata capability remained blocked |

Each file has a provenance header followed by its byte-preserved original
body. The body may describe the pre-execution truth at its original commit;
the table above and the canonical recovery design own the later outcome.

Return to the [documentation archive](../README.md) or the
[operations index](../../operations/README.md).
