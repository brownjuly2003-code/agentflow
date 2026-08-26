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

## Next-session resume contract

This is the only remaining F-19c continuation. Do not repeat the packet,
provenance, cosign, Helm, kind, smoke, or E2E rehearsal merely to refresh
evidence.

| Boundary | Exact resume state |
| --- | --- |
| Git and artifact | Verified source and current `origin/main` are `51be8f2197d9148e6d57cc8340c303afc7189ad8`. Local evidence commit `75a1c9e51b1fa8baf090dd013b90df77326f2057` is not pushed. Genuine build run `32989412486` supplied artifact `9614258460`. |
| Accepted image | `ghcr.io/brownjuly2003-code/agentflow-api@sha256:58dfd77af54502e94b5dc931ecf6b31c9b9872df7c3066057a5b57905e563f5c`. |
| Mac evidence | `/Users/julia/agentflow-fc5-7113966/f19-kind-51be8f2-20260826-codex01/evidence`; corrected attempt `2/5` passed rate-limit E2E `1/1` and remaining E2E `26/26`. |
| Mac runtime | Cluster `agentflow-f19-51be8f2-codex01` is deleted, ports `8080` and `3300` are free, the prior node is restored, and Colima profile `agentflow-fc5-7113966` is stopped with its disks retained. Do not alter `/Users/julia/agentflow-docker-check`. |
| Windows boundary | Do not start or install WSL, Docker, Colima, kind, or an equivalent container runtime on Windows. Any further container/cluster verification belongs on the dedicated Mac. |
| Next external gate | Only after fresh explicit owner authorization, dispatch the real `staging-deploy` workflow with `build_run_id=32989412486`, `source_sha=51be8f2197d9148e6d57cc8340c303afc7189ad8`, and `confirm=PROMOTE`. Push and workflow dispatch remain separate authorization boundaries. |
| Claim boundary | A successful run may create staging-scoped evidence only. It does not establish production rollout, production acceptance, or complete F-19 closure. `production.status` remains `candidate` until the later production boundary passes. |

Before any authorized dispatch, refresh read-only GitHub run/artifact metadata
and confirm that the selected run, source SHA, artifact identity, and workflow
input contract are still exact. If any identity has changed or the artifact is
unavailable, fail closed and report the new blocker; do not substitute a newer
run, rebuild the image, or synthesize a packet.

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
