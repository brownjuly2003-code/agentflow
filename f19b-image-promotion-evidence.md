# F-19b Image Promotion Evidence

## Goal

Turn the digest built, signed, and attested by the protected container workflow into a machine-readable Helm promotion packet without rebuilding the image or claiming a staging rollout.

## Tasks

- [x] Add failing tests for digest validation, exact Helm rendering, and workflow artifact wiring. → Verify: old workflow has no promotion evidence.
- [x] Generate values, deployment manifest, and provenance metadata from `steps.build.outputs.digest`. → Verify: the manifest contains only the built `repository@digest` identity.
- [x] Upload the packet from the build-owning job with pinned Helm tooling. → Verify: the external-digest signing job cannot emit build/promotion evidence.
- [x] Document the remaining staging-consumption boundary and run local plus Mac gates. → Verify: focused tests and static policy checks pass.

## Done When

- [x] One protected build produces one signed/attested digest and a checksumed Helm packet; no push, dispatch, deployment, or production claim occurs locally.
