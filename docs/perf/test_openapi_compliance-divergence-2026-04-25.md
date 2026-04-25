# test_openapi_compliance local divergence - 2026-04-25

## Summary

`test_documented_openapi_snapshot_matches_live_api` failed locally because the
FastAPI-generated `ValidationError` schema differs across installed FastAPI
versions. This was not caused by Python 3.13 itself, DuckDB seed state, stale
uvicorn, or locale/encoding.

## Evidence

Artifacts:

- `docs/perf/live_openapi_local.json`
- `docs/perf/live_openapi_ci.json`

Observed environments:

- Local failing environment: Python 3.13.7, FastAPI 0.128.0, Pydantic 2.12.5, Starlette 0.50.0.
- Project `.venv`: Python 3.13.7, FastAPI 0.135.3, Pydantic 2.12.5, Starlette 1.0.0.
- Docker CI-like install line from `contract.yml`: Python 3.11.15, FastAPI 0.136.1, Pydantic 2.13.3, Starlette 1.0.0.

The only diff between local and CI-like live OpenAPI payloads is:

```diff
@@ -3239,6 +3239,13 @@
            "type": {
              "type": "string",
              "title": "Error Type"
+          },
+          "input": {
+            "title": "Input"
+          },
+          "ctx": {
+            "type": "object",
+            "title": "Context"
            }
```

The project `.venv` on Python 3.13 passed the target test before this fix,
which rules out Python 3.13 as the root cause. The global Python 3.13
environment reproduced the schema mismatch with FastAPI 0.128.0.

## Fix

The contract test now normalizes only the FastAPI-owned
`components.schemas.ValidationError.properties.input` and `ctx` fields before
comparing documented schemas to live schemas.

This keeps the test strict for project-owned schemas and paths while avoiding a
false local failure on a framework-internal validation error schema that changed
between supported FastAPI versions.
