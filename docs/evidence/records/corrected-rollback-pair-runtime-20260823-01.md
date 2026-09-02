# Corrected rollback pair — runtime record (2026-08-23)

**Record ID:** `CORRECTED_ROLLBACK_PAIR_RUNTIME_20260823_01`.
**Result:** **PASS** — the metadata-only probe revision and the corrected
rollback to revision 3 both executed with every protected invariant held.
**Authorization:** owner delegation of 2026-08-23 ("сделай все сам");
context `kind-agentflow-reverify-ed03fc47`, release `agentflow`, namespace
`agentflow`; rollback target 3; revisions 1/2/4 forbidden.

## Preflight (all PASS, read-only)

- Packet `corrected-rollback-pair-20260803-01` file and dependency hashes
  intact; tracked chart inputs match frozen source commit `78742d0`
  (the live-repo copies have drifted since — renders must come from the
  frozen commit, which is what happened).
- Renders reproduced bit-for-bit on BOTH hosts with helm
  `v3.16.3+gcfd0749` (Windows native; on the iMac a staged binary with
  the official checksum `495d75b4…`, system helm 3.15.4 untouched):
  baseline `c281ce6cab5478a8222877dc4361d702aded67db47b96b5a645b03bd9fd2e9e7`,
  probe `c09170d03f838454c6be8ea2502c252bf7270ed56f55e5d4dbb2c62c1bf34044`.
- Live helm revision was exactly 3; the stored rev-3 manifest is
  structurally identical to the frozen baseline (byte hash differs only
  by helm storage formatting; structural three-object comparison equal).
- Zero-failure hold exceeded: job `80e6e2be68fde261e281b847f1a0ae44`
  RUNNING since 13:58:51Z (the post-recovery fresh submit), 854/854
  checkpoints, 0 failed at preflight.
- Identity freeze: CR UID `031f8387-3436-4408-bc99-7fbcd58ccfbc`,
  generation 23; SA `agentflow-soak-rv` UID
  `4bb01109-8257-4670-9a24-c7e081df32f5`; image
  `agentflow-flink-local:78742d0-minpause0-groupoffsets-20260803-01`.
- iMac DNS was down (AdGuard, known pattern) — all artifacts moved via
  `ssh 'cat > file' < local` with hash comparison at both ends; staging
  root `~/agentflow-rollback-pair-20260823-01/`.

## Attempt ledger

### Attempt 1 — probe revision 4: FAILED SAFE (webhook timeout)

Server-side dry-run PASS (manifest ≡ probe, normalized). The real apply
at 17:39:08 MSK failed: flink-operator mutating webhook
`mutationwebhook.flink.apache.org` timed out (10 s) under VM load — the
same webhook had served the dry-run 54 s earlier. The FlinkDeployment was
NOT patched (gen 23, no probe key), revision 3 stayed deployed, and helm
recorded revision 4 as `failed` (left in history as evidence). Per the
packet's no-raw-retry rule the attempt ended there.

### Successor packet

`.codex-grok-tasks/corrected-rollback-pair-20260823-02/` — identical
renders, dependencies, and probe annotation value; `source_revision: 5`;
`forbidden_target_revisions: [1, 2, 4]`; supersession reason recorded in
the contract. Mirrored to the staging root with matching hashes.

### Attempt 2 — probe revision 5 → rollback revision 6: PASS

Dry-run re-verified (manifest ≡ probe) and the apply followed in the same
session window: revision **5** deployed 18:12:26 MSK. Verified at rev 5:
CR UID and generation unchanged (gen 23 — metadata-only, no spec
reconcile), SA UID unchanged, probe annotation
`agentflow.dev/rollback-probe: corrected-rev4-to-rev3-20260803-01`
present, all namespace pods 1/1, job RUNNING with the SAME start-time
`1787493531399` (zero job restarts), checkpoints 1970 completed / 0
failed and growing.

`helm rollback agentflow 3` then recorded revision **6**
("Rollback to 3", deployed 18:13:36 MSK). Verified at rev 6: probe
annotation gone, CR UID `031f8387…` and generation 23 unchanged, all pods
1/1, job RUNNING with the same start-time and 0 failures, checkpoints
1990/0 and growing, and the stored rev-6 manifest **byte-identical** to
the stored rev-3 manifest (`9d555a8351aec0ec5bd2562b91076bf135b12588f6ea4fbce4ad46b33fafdf63`
both).

## Consumed and retained

- Consumed: probe revision numbers 4 (failed) and 5 (superseded), packet
  `corrected-rollback-pair-20260803-01` (superseded) and
  `corrected-rollback-pair-20260823-02` (executed), rollback revision 6.
  Helm history now ends `... 4 failed / 5 superseded / 6 deployed
  Rollback to 3`; never target 1/2/4/5.
- Retained evidence: staging root `~/agentflow-rollback-pair-20260823-01/`
  on the iMac (dry-run outputs, rendered baseline/probe, staged helm) and
  the failed-rev-4 history row. The API `/data` capture
  `~/agentflow-api-data-capture-20260823-01/` is unrelated to this gate
  and stays per its own note.

## Claim boundary

This closes the corrected-rollback mechanics gate: a real Helm revision
pair on the live stand with UID/generation/JID/spec/checkpoint/offset
invariance and a byte-identical restored manifest. It does NOT close the
full-soak gate (F-02 stays `BLOCKED_HOST_CAPACITY` per
`ci-soak-f02-capacity-decision-20260823-01.md`), does not elevate
`production.status` (stays `candidate`), and ran no traffic. The
rollback-after-soak variant on a capable host would need a fresh packet
under the same discipline.
