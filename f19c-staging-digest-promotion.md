# F-19c Staging Digest Promotion

## Goal

Deploy one explicitly selected, successful `container-attestation` image digest to staging without rebuilding it, while preserving the smoke/E2E gate and recording staging-only evidence.

## Tasks

- [x] Select and validate one successful build run plus its exact source SHA before checkout or cluster mutation. → Verify: workflow contracts reject the wrong run, workflow, branch, result, or SHA.
- [x] Download and strictly validate the three-file promotion packet. → Verify: identity, filenames, values, manifest, and checksums fail closed under tampering.
- [x] Verify the exact OCI subject with cosign and GitHub SLSA provenance before kind starts. → Verify: workflow ordering and signer/source constraints are pinned by tests.
- [x] Deploy the packet values through Helm without `docker build` or `kind load`, retaining staging smoke/E2E. → Verify: focused contracts plus an isolated Mac kind rehearsal.
- [ ] Emit staging-only verification evidence and update operational docs. → Verify: docs links, claims, static policy, and scoped diff gates pass.

## Mac Acceptance Status (2026-08-26)

- [x] The clean isolated snapshot at `cd33020` passed the five-file focused
  gate on the Mac: `73 passed in 6.38s` with project Python 3.13.7,
  `PYTHONPATH=$PWD/src`, and the checksum-verified Helm 3.16.3 binary.
- [x] An isolated exact-`51be8f2` kind rehearsal consumed the genuine promotion
  packet from successful build run `32989412486`, independently verified its
  packet, GitHub provenance, and cosign identity, then deployed exact subject
  `ghcr.io/brownjuly2003-code/agentflow-api@sha256:58dfd77af54502e94b5dc931ecf6b31c9b9872df7c3066057a5b57905e563f5c`
  without `docker build` or `kind load`. Smoke passed, the rate-limit split
  passed `1/1`, and the remaining E2E suite passed `26/26` on corrected attempt
  `2/5`. The unique cluster was deleted, the retained project node was restored,
  and the dedicated Colima profile was gracefully stopped with its disks kept.
- [ ] The real `staging-deploy` workflow and its staging evidence remain open;
  the local rehearsal is not a staging rollout or production acceptance.

## Done When

- [ ] A manual staging run can consume only the selected signed/attested digest, pass smoke/E2E, and upload evidence that explicitly does not claim production rollout, production acceptance, or complete F-19 closure.

## Notes

No workflow dispatch, new image push/signing/attestation, real staging or
production deployment, publication, or Windows Docker/WSL action occurred.
The isolated kind deployment proves only the local consumer path. Closing the
remaining staging-evidence item requires an authorized real `staging-deploy`
dispatch with the retained genuine packet; that dispatch remains an explicit
external gate.

The retained Mac evidence is under
`/Users/julia/agentflow-fc5-7113966/f19-kind-51be8f2-20260826-codex01/evidence`.
Attempt `1/5` failed only at test collection because the borrowed venv lacked
the workflow's editable SDK install; its cleanup succeeded. Attempt `2/5` used
the snapshot's `src` and `sdk` roots, and its `result.txt`, cleanup log, and two
E2E logs have SHA-256 values `b22b5bb6...9d8340`, `68797222...116d8`,
`f02cfe17...e52b6`, and `852134d0...42869`, respectively.
