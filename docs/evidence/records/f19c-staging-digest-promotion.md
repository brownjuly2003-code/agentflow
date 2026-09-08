# F-19c Staging Digest Promotion

## Goal

Deploy one explicitly selected, successful `container-attestation` image digest to staging without rebuilding it, while preserving the smoke/E2E gate and recording staging-only evidence.

## Tasks

- [x] Select and validate one successful build run plus its exact source SHA before checkout or cluster mutation. → Verify: workflow contracts reject the wrong run, workflow, branch, result, or SHA.
- [x] Download and strictly validate the three-file promotion packet. → Verify: identity, filenames, values, manifest, and checksums fail closed under tampering.
- [x] Verify the exact OCI subject with cosign and GitHub SLSA provenance before kind starts. → Verify: workflow ordering and signer/source constraints are pinned by tests.
- [x] Deploy the packet values through Helm without `docker build` or `kind load`, retaining staging smoke/E2E. → Verify: focused contracts plus an isolated Mac kind rehearsal.
- [x] Emit staging-only verification evidence and update operational docs. → Verify: authorized run `33005146264` passed and artifact `9620326516` carries the bounded staging-only claim.

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
- [x] The authorized real `staging-deploy` run `33005146264` consumed build run
  `32989412486`, passed digest-only deploy, rate-limit and remaining E2E gates,
  tore down the staging cluster, and uploaded evidence artifact `9620326516`.
  This is staging acceptance only, not production rollout or acceptance.

## Completion and next-session boundary

F-19c is complete at the staging boundary. Do not repeat the packet,
provenance, cosign, Helm, kind, smoke, E2E, or real staging deployment merely
to refresh evidence. Production rollout and acceptance remain a separate F-19
boundary that needs its own plan and fresh explicit owner authorization.

| Boundary | Exact resume state |
| --- | --- |
| Git and build artifact | Verified source and current `origin/main` are `51be8f2197d9148e6d57cc8340c303afc7189ad8`. Genuine build run `32989412486` supplied artifact `9614258460`; no local evidence commit was pushed. |
| Accepted image | `ghcr.io/brownjuly2003-code/agentflow-api@sha256:58dfd77af54502e94b5dc931ecf6b31c9b9872df7c3066057a5b57905e563f5c`. |
| Mac evidence | `/Users/julia/agentflow-fc5-7113966/f19-kind-51be8f2-20260826-codex01/evidence`; corrected attempt `2/5` passed rate-limit E2E `1/1` and remaining E2E `26/26`. |
| Mac runtime | Cluster `agentflow-f19-51be8f2-codex01` is deleted, ports `8080` and `3300` are free, the prior node is restored, and Colima profile `agentflow-fc5-7113966` is stopped with its disks retained. Do not alter `/Users/julia/agentflow-docker-check`. |
| Windows boundary | Do not start or install WSL, Docker, Colima, kind, or an equivalent container runtime on Windows. Any further container/cluster verification belongs on the dedicated Mac. |
| Staging evidence | Run `33005146264` completed successfully and uploaded artifact `9620326516`, named `agentflow-staging-promotion-51be8f2197d9148e6d57cc8340c303afc7189ad8-33005146264`, with archive digest `sha256:5872a04baa5ba4b2f5b95eb906e482a5c8dd66aae5fbf21b416dbd7542f013cf`. |
| Next external gate | F-19c has no remaining staging work. Any production rollout or acceptance is a new external boundary with a separate plan and fresh explicit owner authorization; the staging `PROMOTE` dispatch must not be reused as production evidence. |
| Claim boundary | The successful run proves only that the selected digest passed the staging smoke and E2E gates. It does not establish production rollout, production acceptance, or complete F-19 closure. `production.status` remains `candidate`. |

Do not redispatch staging to refresh timestamps or artifacts. Before any later
production action, define and verify a production-specific rollout and
acceptance contract; do not treat the staging evidence as production evidence.

## Done When

- [x] A manual staging run consumed only the selected signed/attested digest, passed smoke/E2E, and uploaded evidence that explicitly does not claim production rollout, production acceptance, or complete F-19 closure.

## Notes

The owner-authorized real staging run `33005146264` was dispatched once and
approved only for the `staging` environment. It completed successfully after
the exact build, packet, cosign, provenance, digest-only deploy, smoke/E2E,
teardown, evidence-recording, and artifact-upload gates. No push, new image
build/push/signing/attestation, production deployment, publication, or Windows
Docker/WSL action occurred. The Mac VM remained stopped.

The retained staging artifact is `9620326516`; its downloaded
`staging-promotion.json`, `cosign-verify.json`, and
`github-attestation.json` SHA-256 values are
`a11a26fe9b2cd8b0003b30cfd33c032a4b46b405eb79a7dfa748cd927b159ce2`,
`628aa75b491ca002f134dcd6722bb511d642b90c198ae05fe9902f0fa7492bcf`, and
`209cb195a985cd2402ea9bb82b992819d1db7b9ca9e5cbabdf0e5b1095937790`.
The artifact is also retained locally under
`.artifacts/staging-promotion-run-33005146264`.

The retained Mac evidence is under
`/Users/julia/agentflow-fc5-7113966/f19-kind-51be8f2-20260826-codex01/evidence`.
Attempt `1/5` failed only at test collection because the borrowed venv lacked
the workflow's editable SDK install; its cleanup succeeded. Attempt `2/5` used
the snapshot's `src` and `sdk` roots, and its `result.txt`, cleanup log, and two
E2E logs have SHA-256 values `b22b5bb6...9d8340`, `68797222...116d8`,
`f02cfe17...e52b6`, and `852134d0...42869`, respectively.
