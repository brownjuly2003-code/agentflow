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
the table above and the
[current recovery design](../../operations/api-duckdb-persistence-recovery-design.md)
own the later outcome.

## API DuckDB recovery chronology

The interleaved 2026-08-10 to 2026-08-23 design-and-execution snapshot is
historical only and not executable. Current preservation, recovery, and
authorization boundaries belong to the current design.

| Record | Boundary | Current owner |
| --- | --- | --- |
| [API DuckDB recovery chronology](api-duckdb-persistence-recovery-chronology-2026-08-10-to-2026-08-23.md) | Historical snapshot; do not execute or treat as current truth | [API DuckDB persistence and recovery design](../../operations/api-duckdb-persistence-recovery-design.md) |

Return to the [documentation archive](../README.md) or the
[operations index](../../operations/README.md).
