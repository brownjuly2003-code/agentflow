# T12 - Staging Deploy: make webhook callback test pass reliably

**Priority:** P1 - **Estimate:** 1-3ч

## Goal

Сделать `Staging Deploy` green без вырезания webhook coverage из staging E2E.

## Context

- Latest staging run on `main`: `24817461777` for SHA `a010a2d`.
- Helm/kind deploy succeeds far enough for the workflow to pass 15 of 16 selected E2E tests.
- The only red check is `tests/e2e/test_smoke.py::test_webhook_test_endpoint_delivers_callback`.
- Failure detail: the test waits on `webhook_receiver["events"].get(timeout=5)` and ends with `_queue.Empty`, then `Failed: Webhook callback was not received within 5 seconds.`
- This points to a staging-only callback delivery problem: networking, callback host reachability, background delivery timing, or environment-specific config mismatch.

## Deliverables

1. Trace the callback path used by the staging E2E test end-to-end.
2. Determine whether the failure is caused by:
   - unreachable callback receiver,
   - delayed async delivery,
   - or staging-specific webhook configuration.
3. Implement the minimal fix that preserves real callback verification.
4. Get one green recent run for `Staging Deploy`.

## Acceptance

- `test_webhook_test_endpoint_delivers_callback` passes in the staging workflow.
- The full staging E2E subset is green after deploy.
- The fix preserves an actual callback round-trip and does not replace it with a mock/skip.

## Notes

- Do not solve this by deleting the webhook test from staging.
