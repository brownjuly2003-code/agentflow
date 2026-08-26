# F-19a Helm Digest Contract

## Goal

Make every Helm-managed API-derived workload consume one immutable API image digest, let Flink use the same digest-aware value shape, preserve the tag-based developer default, and refuse tag-only production renders.

## Tasks

- [x] Add failing Helm tests for digest rendering, schema validation, and the production refusal. → Verify: focused tests fail for the missing contract.
- [x] Add `image.digest`, a shared image-reference helper, and the production guard. → Verify: all API-derived workload images render as the same `repository@sha256:...`.
- [x] Document the environment-owned digest and the remaining F-19 boundary. → Verify: docs-link and claims checks remain green.
- [x] Run the focused local checks and one clean Mac gate without local Docker/WSL. → Verify: scoped tests and static gates pass on the intended host.

## Done When

- [x] Development defaults still render `repository:tag`; production requires a valid digest; no claim says the wider build/promote workflow is complete.
