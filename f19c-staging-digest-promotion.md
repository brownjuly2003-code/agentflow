# F-19c Staging Digest Promotion

## Goal

Deploy one explicitly selected, successful `container-attestation` image digest to staging without rebuilding it, while preserving the smoke/E2E gate and recording staging-only evidence.

## Tasks

- [x] Select and validate one successful build run plus its exact source SHA before checkout or cluster mutation. → Verify: workflow contracts reject the wrong run, workflow, branch, result, or SHA.
- [x] Download and strictly validate the three-file promotion packet. → Verify: identity, filenames, values, manifest, and checksums fail closed under tampering.
- [x] Verify the exact OCI subject with cosign and GitHub SLSA provenance before kind starts. → Verify: workflow ordering and signer/source constraints are pinned by tests.
- [ ] Deploy the packet values through Helm without `docker build` or `kind load`, retaining staging smoke/E2E. → Verify: focused contracts plus an isolated Mac kind rehearsal.
- [ ] Emit staging-only verification evidence and update operational docs. → Verify: docs links, claims, static policy, and scoped diff gates pass.

## Mac Acceptance Status (2026-08-26)

- [x] The clean isolated snapshot at `cd33020` passed the five-file focused
  gate on the Mac: `73 passed in 6.38s` with project Python 3.13.7,
  `PYTHONPATH=$PWD/src`, and the checksum-verified Helm 3.16.3 binary.
- [ ] The kind rehearsal remains gated by a genuine workflow-built promotion
  packet. `cd33020` is not on `origin/main`, GitHub has no matching
  `container-attestation` run, and no active `agentflow-image-promotion-*`
  artifact exists. No packet was synthesized, and Docker/kind was not started.

## Done When

- [ ] A manual staging run can consume only the selected signed/attested digest, pass smoke/E2E, and upload evidence that explicitly does not claim production rollout, production acceptance, or complete F-19 closure.

## Notes

No workflow dispatch, image push, signing, attestation, deployment,
publication, or Windows Docker/WSL action is part of this local implementation
slice. Closing the remaining acceptance items requires a genuine packet from
the protected build workflow; push and workflow dispatch remain explicit
external gates.
