# CI-soak r10 orchestration stop — 2026-08-21

## Goal

Execute one newly authorized post-fix `--count 2000` rehearsal from exact
source HEAD `1fc959efcc1c871fd3057f27a8aef60db44fc878`, using fresh r10
identities and unconditional protected-co-tenant restoration.

## Fixed r10 identities

| Identity | Reserved value |
| --- | --- |
| Source/gate HEAD | `1fc959efcc1c871fd3057f27a8aef60db44fc878` |
| Snapshot | `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-1fc959e-r10` |
| Compose project | `agentflow-ci-soak-1fc959e-r10` |
| Output | `.artifacts/soak-rehearsal-2000-1fc959e-r10` under the snapshot |
| Preflight attempt | `ci-soak-1fc959e-r10-preflight` |
| Rehearsal attempt | `ci-soak-1fc959e-r10-rehearsal-20260821-01` |
| Grok run | `deproject-ci-soak-r10-20260821-01` |

## Local gate and source evidence

The fresh exact-HEAD architecture gate passed before delegation:

```text
ARCHITECTURE_READY=PASS blockers=0 head=1fc959efcc1c871fd3057f27a8aef60db44fc878
```

Codex created one exact `git archive` in the ignored r10 control directory:

- path:
  `.codex-runtime/ci-soak-r10-rehearsal-20260821-01/source-1fc959e.tar`;
- size: `17,971,200` bytes;
- SHA-256:
  `26467251f43d17307d7f6e0d2e88b25f70c8a75f9d6680f7460024a91c9e96ed`.

The archive was never transferred to the Mac. It is local control evidence,
not a runtime snapshot.

## Grok orchestration outcome

The bounded executor used `local_grok_cli` with pinned requested model
`grok-4.6`, `dontAsk`, strict sandbox, web and subagents disabled, and no
permission bypass. Prompt SHA-256 was
`dffecc2040e863f75012f784587a19876f14a9926b73d3c1775e3eb105ff2bd5`;
attempt fingerprint was
`9a68c0d9ef0bc6418f294df89f3bbbe6e8cb172285936b5ad20a88cb3e3ba47b`.

The process remained alive for all six permitted status polls over roughly
nine minutes but emitted no terminal stdout or stderr. It was cancelled once
at the monitoring limit, and no duplicate or QA run was launched. The exact
stdout and stderr files are both zero-byte artifacts with SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
launch metadata SHA-256 is
`a5941c0da22c59e3a6cfa0e6e6dcb8213a2ee10212656b183d8e42700df9d7e0`.
No completed Grok result exists, so no actual-model usage claim is available.

Grok created no r10 control file and did not modify the source archive,
tracked files, ignored handoffs, or any protected source. Protected local
hashes and clean tracked worktree/index were independently rechecked.

## Independent external safety proof

After cancellation, Codex ran one byte-exact read-only SSH postflight. Its
first execution exposed only two probe-format defects: containers without a
Docker healthcheck produced blank display rows, and PowerShell stdin added a
terminal carriage return. The remote facts already showed no mutation. One
narrow correction changed only display formatting and byte-exact stdin
delivery; the single rerun exited `0`. The final local probe SHA-256 is
`4b28d1ba7a398b76024bbc9484946044fe851b7249d71cd22c6d586db655a976`.

The final read-only evidence proved:

- r10 snapshot, remote control directory, output, and preflight evidence were
  all absent;
- owner lock and r10 controller process were absent;
- r10 project containers/networks/volumes were `0/0/0` and all four possible
  r10 probe-container counts were zero;
- MinIO, Iceberg REST, dual-route ClickHouse, and Kind retained their exact
  recorded IDs, names, `running` state, and restart count `0`;
- MinIO and ClickHouse were healthy; MinIO live, Iceberg `/v1/config`, host
  and Kind ClickHouse `SELECT 1`, Kind `/livez`, and exactly one
  kube-apiserver all passed;
- the rollback ClickHouse remained at its exact ID, `exited(0)`, restart count
  `0`, with no network attachment;
- the Mac checkout remained at
  `ae9fb69db7de737b469f868f218e8d623c206959` with exactly its three
  established untracked paths.

## Classification and next boundary

This slice is `ORCHESTRATION_STOP_BEFORE_MUTATION`. It is neither rehearsal
PASS nor rehearsal FAIL:

```text
STOP_COMMAND=NOT_INVOKED
CONTROLLER=NOT_INVOKED
REMOTE_R10_IDENTITIES=ABSENT
PROJECT_RESOURCES=0/0/0
OWNER_LOCK=ABSENT
```

The r10 attempt name, prompt, local control directory, and authorization are
consumed orchestration evidence. Do not resume or reuse them. A later external
attempt must use fresh r11-or-later snapshot/project/output/control/attempt
identities, a new exact-HEAD gate and preflight, and new explicit
authorization. No full soak, rollback exercise, retained-evidence cleanup,
production action, fetch, or push occurred or became authorized.
