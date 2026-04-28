# T31 - Hashed API-key auth cache

**Status:** Ready for review/commit
**Priority:** P2
**Track:** Auth performance / release hygiene

## Goal

Avoid repeated bcrypt verification for the same successfully authenticated
hashed API key. The first successful `key_hash` match should cache the runtime
plaintext in `AuthManager`, so later requests can use the existing
`keys_by_value` fast path.

## Context

- Branch: `main`
- Current HEAD before commit: `b2c0bc0`
- Working tree files for this task:
  - `src/serving/api/auth/manager.py`
  - `tests/unit/test_auth.py`
  - `docs/release-readiness.md`
  - `docs/codex-tasks/2026-04-28/T31-hashed-api-key-auth-cache.md`
- This closes the old performance note that bcrypt verify could run on every
  auth check for hash-only API-key configs.

## Implementation

- `AuthManager.authenticate()` now stores a successful current-key hash match in
  `_runtime_plaintext_by_hash` and `keys_by_value`.
- The returned `TenantKey` still sets `matched_slot="current"`.
- No rotation-path behavior changed; previous-key grace-period checks still use
  the existing `previous_key_hash` path.

## Regression Test

`tests/unit/test_auth.py::test_hashed_key_authentication_caches_successful_plaintext`
loads a hash-only key, monkeypatches `verify_api_key`, authenticates the same
plaintext twice, and asserts that hash verification runs only once.

## Verification Evidence

- Targeted test: `1 passed in 1.19s`
- `tests/unit/test_auth.py`: `11 passed, 1 warning in 3.26s`
- `tests/unit`: `433 passed in 81.64s`
- `tests/contract tests/e2e`: `35 passed in 150.54s`
- Full suite: `724 passed, 4 skipped in 498.66s`

## Local Windows Test Note

Direct pytest on this workstation can hang before output when `platform.*`
reaches Windows WMI through `pyreadline3`, `pytest-metadata`, or
`prometheus_client`. The successful local verification used:

- Redis running through `docker compose up -d redis`
- project-local `TEMP`/`TMP`, `--basetemp`, and pytest cache paths
- `-p no:schemathesis -p no:metadata`
- a dummy `readline` module in the Python test runner
- a temporary project-local `sitecustomize` shim so e2e API subprocesses avoid
  the same WMI hang

The shim was removed after verification. Do not commit local `.tmp` test shims.

## Next Session Plan

1. Re-check `git status --short`.
2. Review the four intended files.
3. Commit with explicit pathspecs only.
4. Push `main` if release handoff should continue on origin.
5. After CI is green, proceed with the approved `v1.1.0` retag/publish workflow.
