# Engineering Status

> Updated: **2026-08-09** (clean-checkout PyFlink OCI build + submission smoke
> **PASS**; Flink Kubernetes Operator + Helm golden-topology deploy **PASS**;
> live Iceberg materialization from `events.validated` **PASS** at the direct
> topic boundary; full lake-to-serving single-event smoke **PASS** on the
> mixed-SHA stand; isolated checkpoint restore/replay **PASS** with exact
> no-duplicate lake/serving assertions; golden 4h soak/rollback canary
> **`FAIL_CANARY_CATCHUP_RATE_FLOOR`** — baseline and delivery passed, exact
> catch-up failed; the corrected revision-3 recovery later reached
> **`RUNTIME_HOLD_PASS`** in a 930-second read-only readiness-baselined hold
> (completed checkpoints `7675→8614`, failed `1→1`, delta `0`); a later kind
> residual canary **PASS** unlocked soak attempts; latest identity
> `golden-4h-soak-rv-20260807-05` producer **PASS** (`1_440_000` delivered,
> failures `0`) but overall soak **`SOAK_FAIL`** on terminal Flink health
> before dual-mean verify could PASS — corrected rollback **not started**
> ([perf/golden-4h-soak-05-failure-2026-08-08.md](perf/golden-4h-soak-05-failure-2026-08-08.md));
> external pentest evidence audit **`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`**
> (evidence/readiness only; not a pen-test; gate open); GitHub Environment
> `npm` approval protection **PASS** (one required reviewer; gate closed);
> core-only API and hardened runtime-image remediation locally
> **PASS**; golden topology remains a production candidate, not production
> accepted) · release line **`v2.0.0`**. Numbers below come only from measured,
> in-repo evidence — see the linked reports for methodology and reproduction
> commands.

AgentFlow's product axis — **event → live metric** on the real streaming path
(Kafka → PyFlink → `events.validated` → serving bridge → ClickHouse → API
with Redis push invalidation) — is implemented, measured, and documented. The
Iceberg materializer, operator-compatible image, and Helm workload are
implemented and locally contract-tested. On 2026-07-30 a clean-checkout OCI
build and real Flink job submission smoke passed on `deproject-mac`, and a
later clean kind + Operator + Helm acceptance of exact HEAD `36ed1ec` also
passed (stable hold, growing checkpoints, zero leadership flaps; Kafka on
that stand used live runtime fixes, later captured in the tracked kind
acceptance scaffold `k8s/acceptance/kafka-kraft.yaml` — not production Kafka).
On 2026-08-01 live Iceberg materialization from direct `events.validated`
injection **PASS**ed on the mixed-SHA stand (Operator base `36ed1ec`,
materializer runtime source `ed03fc47`) — see
[perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md).
The same day, an independently verified full one-event lake-to-serving smoke
also **PASS**ed
([perf/full-lake-to-serving-e2e-2026-08-01.md](perf/full-lake-to-serving-e2e-2026-08-01.md)):
`orders.raw` → PyFlink → `events.validated` → {Iceberg; bridge → ClickHouse →
API}. That closes the single-event hop chain only; it is not full
production acceptance. On 2026-08-02 an isolated checkpoint restore/replay
run **PASS**ed with distinct J1/J2, exact savepoint restore linkage, E1/E2
present once on all measured lake/serving surfaces, DLQ `0`, and source lag
`0` — see
[perf/checkpoint-restore-replay-2026-08-02.md](perf/checkpoint-restore-replay-2026-08-02.md).
The 2026-08-01 resource preflight remains historical. A later isolated stand
reached the canary: zero baseline **PASS**, producer delivery `2000/2000` with
failures `0`, then verifier **`FAIL_CANARY_CATCHUP_RATE_FLOOR`** at ClickHouse
pipeline `1092/2000` and orders `546/2000`. The 4h producer, observer, and
rollback were **not started**. The next preflight found that clean rev1/rev2
had already been installed with interval `1000`, JM CPU `0.5`, and TM CPU `1`.
It stopped at **`BLOCKED_RUNTIME_MIN_PAUSE_NOT_RENDERED`**: runtime source
`ed03fc47` does not render checkpoint minimum pause, the active CR omits it,
and observed checkpoint cadence remains ~30 s. That reinstall also replayed
the immutable canary1 events (validated end offset `4000`, all task group lags
`0`); no canary2 Job or evidence exists — see
[perf/golden-4h-soak-canary-failure-2026-08-02.md](perf/golden-4h-soak-canary-failure-2026-08-02.md).
Tracked commit `78742d0` now adds a default-preserving, fail-closed
`group-offsets` cutover mode and the verified recovery pack renders min-pause
`0 ms`. Its first authorized stand preflight stopped before staging/build/Helm at
**`BLOCKED_RESOURCE_HEADROOM_BEFORE_SAFE_CUTOVER`**: Kind
`MemAvailable=1,683,140 kB` was below the required `1,900,000 kB`. A later
controlled cutover deployed the corrected revision 3, and the separately
authorized read-only readiness-baselined checkpoint hold then returned
**`RUNTIME_HOLD_PASS`**: over `930 s`, completed checkpoints advanced
`7675→8614` (`+939`, required `837`) while failed checkpoints remained `1`
(delta `0`). No traffic, runtime mutation, canary2, soak, or rollback occurred
during that hold — see
[perf/ready-baselined-checkpoint-hold-2026-08-03.md](perf/ready-baselined-checkpoint-hold-2026-08-03.md).
A later kind residual canary **PASS** unlocked soak traffic
([perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md](perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md));
multiple soak identities were attempted; latest
`golden-4h-soak-rv-20260807-05` producer **PASS**ed but overall soak
**`SOAK_FAIL`**ed on terminal Flink health before dual-mean verify could PASS;
corrected rollback was **not started** — see
[perf/golden-4h-soak-05-failure-2026-08-08.md](perf/golden-4h-soak-05-failure-2026-08-08.md).
External security acceptance remains open. Read-only external-pentest
evidence/readiness audit at `2026-08-01T17:11:58Z` returned
**`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`** (intake not present/unclaimed; all seven
gate criteria fail; no repository-visible or public-GitHub third-party evidence;
**not** a penetration test) — see
[operations/external-pentest-evidence-blocker-2026-08-01.md](operations/external-pentest-evidence-blocker-2026-08-01.md).
Read-only GitHub API verification of Environment `npm`, recorded at
`2026-08-03T03:18:11Z`, is **PASS**: the exact Environment exists with one
non-empty `required_reviewers` rule for user `brownjuly2003-code`. Self-review
is permitted, so this is not a four-eyes claim — see
[operations/npm-environment-approval-2026-08-03.md](operations/npm-environment-approval-2026-08-03.md).
The earlier 4 h @ 100 eps result remains valid evidence for its measured
pre-materializer path only (advisory for the post-Iceberg golden gate).
Tracked full-smoke evidence is recorded in local evidence commit `cf247ba`
(local-only, unpushed).

Closing CI hardening on 2026-07-30 also verified the Python 3.11/3.12/3.13
compatibility lanes, made `pyiceberg` optional for the core-only API path,
aligned SDK examples with Ruff 0.16 Markdown formatting, and removed
`pip`/`setuptools`/`wheel` from the final API image after `pip check`.
A later dependency-resolution gate now keeps the Iceberg write path complete
with Python 3.13-compatible `pyiceberg-core==0.7.0` and holds the optional MCP
integration on its supported 1.x API.
A clean core-only HTTP smoke returned 200 for health, entity, and NL query.
An independent Mac rebuild scanned with Trivy 0.70.0 at zero HIGH/CRITICAL
findings; see
[security-runtime-image-trivy-2026-07-30.md](security-runtime-image-trivy-2026-07-30.md).
The dependency failure, resolution, and clean Mac verification are recorded in
[dependency-compatibility-2026-07-30.md](dependency-compatibility-2026-07-30.md).
All repository-owned coverage floors remain blocking. The Codecov upload and
badge were removed (audit F-06, 2026-08-21): the repository was never enabled
in the external service, the upload failed with "Repository not found", and
the test job no longer carries the `id-token: write` capability that existed
only for that upload. History in
[operations/codecov-setup.md](operations/codecov-setup.md).
The exact post-remediation GitHub SHA must still complete all required checks
before the external closure gate is claimed.

**Project lifecycle:** closure candidate. Engineering scope is frozen; the
production-candidate boundary, future acceptance program, and release gates are
recorded in [PROJECT_CLOSURE.md](PROJECT_CLOSURE.md).

## Proven

| Claim | Result | Evidence |
|-------|--------|----------|
| Real-path freshness e2e | **3.02 s p50 / 5.70 s p95** (n=20) | [perf/freshness-e2e-realpath.md](perf/freshness-e2e-realpath.md) |
| In-process demo freshness | 1.06 s p50 / 1.99 s p95 | [freshness-benchmark.md](freshness-benchmark.md) |
| Real-path throughput measured | produce ~700 eps; bridge apply is the ceiling (see below) | [perf/throughput-realpath.md](perf/throughput-realpath.md) |
| 2-pod control plane on kind | webhook registered on pod A visible on pod B; verify script PASS | [perf/e4-2pod-topology-2026-07-09.md](perf/e4-2pod-topology-2026-07-09.md) |
| E4 Checks 1–4 (2 pods, delivery + alert single-page) | **PASS** on kind | [perf/e4-check4-alert-single-page-2026-07-17.md](perf/e4-check4-alert-single-page-2026-07-17.md) |
| 4 h endurance soak (real path + API reads) | bounded lag (peak 2 915 → 0), bridge RSS/FD flat, one faulted batch replayed exactly-once by the journal guard, **zero cache drift** | [perf/soak-s11-2026-07-10.md](perf/soak-s11-2026-07-10.md) |
| At-scale on own data (S13) | **51.2 M rows / 2.87 M orders / 4 years of legend history**, analyst queries 20–730 ms, all 17 at-scale correctness checks pass (10 row reconciliations + 5 §12 invariants + 2 distributions) incl. full-scan GTIN validation; §12's 12 invariants are pinned in full by 15 unit tests | [perf/scale-own-data-2026-07-11.md](perf/scale-own-data-2026-07-11.md) |
| Security pass (offline/unit remainder) | closed; third-party pen-test **not** claimed | [security-s12-2026-07-09.md](security-s12-2026-07-09.md), [security-audit.md](security-audit.md) |
| Multi-tenant ClickHouse write key | adversarial two-tenant suite green on live CH 25.3 (CI `test-integration` + audit stand) | [security-audit.md](security-audit.md), `tests/integration/test_clickhouse_tenant_isolation_live.py` |
| Clean-checkout PyFlink OCI build + submission smoke | PASS clean-checkout OCI build + submission smoke on 2026-07-30 — image built, JobID `RUNNING`, not Operator/E2E | [perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md) |
| Flink Kubernetes Operator + Helm golden deploy | PASS clean kind Operator/Helm deploy of verified image on exact HEAD `36ed1ec` — CR/job stable, checkpoints `2→23`, leader flaps `0`, not lake E2E | [perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md) |
| Live Iceberg materialization from `events.validated` | PASS direct topic injection → `ed03fc47` lake materializer → live Iceberg exact identity once; narrower gate still valid, now complemented by full one-event path | [perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md) |
| Full lake-to-serving single-event smoke | PASS mixed-SHA one event through `orders.raw` → PyFlink → `events.validated` → {Iceberg; bridge → ClickHouse → API}; not production acceptance, restore/replay, soak, or multi-tenant | [perf/full-lake-to-serving-e2e-2026-08-01.md](perf/full-lake-to-serving-e2e-2026-08-01.md) |
| Checkpoint restore/replay | PASS isolated E1 → checkpoint/savepoint → byte-identical E1 replay + E2 → distinct restored J2; both identities exact once across Kafka/Iceberg/ClickHouse/API, DLQ 0, lag 0 | [perf/checkpoint-restore-replay-2026-08-02.md](perf/checkpoint-restore-replay-2026-08-02.md) |
| Readiness-baselined checkpoint hold | **`RUNTIME_HOLD_PASS`** for the corrected revision-3 job: 930 s, completed `7675→8614`, failed `1→1`; read-only and no traffic; not canary, soak, rollback, or production acceptance | [perf/ready-baselined-checkpoint-hold-2026-08-03.md](perf/ready-baselined-checkpoint-hold-2026-08-03.md) |
| GitHub Environment `npm` approval protection | PASS exact Environment binding + non-empty `required_reviewers` rule for one User; self-review permitted, not a four-eyes claim | [operations/npm-environment-approval-2026-08-03.md](operations/npm-environment-approval-2026-08-03.md) |
| Hardened API runtime image (local acceptance) | core-only API import/HTTP smoke PASS; Trivy 0.70.0 reports 0 HIGH/CRITICAL after runtime installer removal | [security-runtime-image-trivy-2026-07-30.md](security-runtime-image-trivy-2026-07-30.md) |
| Python cloud/MCP dependency compatibility (local + isolated Mac) | 2170 unit/property tests PASS; MCP 1.29 + PyIceberg 0.11.1/core 0.7.0 clean environment and 39 focused tests PASS | [dependency-compatibility-2026-07-30.md](dependency-compatibility-2026-07-30.md) |

## 2026-07-23 audit closure

| Area | Locally verified state |
|------|------------------------|
| Claims and documentation | machine-readable topology, runtime, SDK, Python, and quality claims agree; 14 project-claims tests pass and strict MkDocs builds |
| Runtime and deployment | pinned PyFlink 2.3 OCI definition and Helm `FlinkDeployment` agree; Helm lint passes and 32 Helm contract tests pass |
| CDC and materializers | fail-closed CDC attribution plus separate Iceberg and ClickHouse consumers; 43 CDC and 56 lake/serving component tests pass |
| SDKs | checked Python/TypeScript capability matrix; TypeScript typecheck and all 50 Vitest tests pass |
| Lifecycle and query paths | role-aware lifecycle, deterministic partial search status, canonical tenant-scoped session job, and bounded HTTP readiness deadline are covered by targeted tests |
| Acceptance boundary | clean build/submission smoke, Operator/Helm deploy, direct live Iceberg materialization, full one-event lake-to-serving smoke, checkpoint restore/replay, npm Environment approval protection, and the corrected revision-3 readiness-baselined hold now measured; the hold is `RUNTIME_HOLD_PASS`; kind residual canary later PASS; latest 4h soak identity `-05` is `SOAK_FAIL` (producer PASS, dual-mean ABORT, corrected rollback not started); external pen-test evidence audit `BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE` (not a pen-test; gate open) |

## Bridge write-path throughput — drain ceiling measured

The bridge apply rate is the honest product ceiling; it has been raised in
measured steps on the same Mac compose stand (Kafka → Flink → bridge → CH):

| Step | Bridge apply | State |
|------|-------------:|-------|
| Baseline (per-event apply) | ~8 eps | measured |
| Q1.2 — ClickHouse-only sink, no scratch lake | 11.4 eps | measured |
| Q1.3 — multi-row batch apply | 22.9 eps | measured — [perf/throughput-realpath-q13-2026-07-09.md](perf/throughput-realpath-q13-2026-07-09.md) |
| Q1.4 — batched session/user read-modify-writes (constant round-trips per batch) | **87.4 eps** | measured — [perf/throughput-realpath-q14-2026-07-10.md](perf/throughput-realpath-q14-2026-07-10.md) |
| Stretch try — 2000-event drain on same Mac class | **107.3 eps** | measured — [perf/throughput-realpath-100eps-try-2026-07-17.md](perf/throughput-realpath-100eps-try-2026-07-17.md) |
| Paced 10 min @ 100 eps produce | **96.5 apply / 97.1 flink / 100 produce** | measured — [perf/throughput-realpath-paced100-2026-07-17.md](perf/throughput-realpath-paced100-2026-07-17.md) |
| Paced **1 h** @ 100 eps produce | **99.5 apply / 99.5 flink / 100 produce** | measured — [perf/throughput-realpath-paced100-1h-2026-07-17.md](perf/throughput-realpath-paced100-1h-2026-07-17.md) |
| Paced **4 h** @ 100 eps produce (r4) | **99.9 apply / 99.9 flink / 100.0 produce** — 1 440 000 events, dup = 0, failures = 0, lag 0 → 0, 0 Flink restarts | measured — [perf/throughput-realpath-paced100-4h-r4-2026-07-19.md](perf/throughput-realpath-paced100-4h-r4-2026-07-19.md) |

The series target of **≥ 80 eps** is met on the 400-burst profile. A
**2000-event** drain cleared at **107.3 eps**. Paced ingress at 100 eps held
for 10 min, 1 h, and — closing the multi-hour gate — **4 h** (r4:
`produced = validated = applied = 1 440 000` exactly, 0 duplicates,
0 failures, lag ends at 0, zero Flink restarts). The two failed 4 h attempts
before r4 are written up honestly in the r4 report (stand disk exhaustion;
bench producer losing a broker self-fence) — neither was an apply-path
defect. Semantics of the batched path are in
[serving-bridge.md](serving-bridge.md).

## Known issues

- **Multi-tenant ClickHouse — proven live (audit P0-1).** The boundary is the
  `tenant_id` **column**, leading each serving table's write key on both stores
  ([ADR-004](decisions/004-tenant-id-column-over-schema-per-tenant.md)). DuckDB
  remains covered by example and property suites; ClickHouse is covered by
  `tests/integration/test_clickhouse_tenant_isolation_live.py` on live server
  25.3 (CI `test-integration` service + audit Mac stand). Cross-tenant lookups
  404, aggregates stay tenant-scoped, and `assert_tenant_key()` refuses an old
  single-column sorting key. Broader isolation across every external dependency
  is still out of scope — see [security-audit.md](security-audit.md).

- **API RSS growth under steady load — fixed and verified live** (was 175 MB
  → 1.67 GB over the 4 h soak; the bridge stayed flat). The webhook
  dispatcher re-materialized the whole `pipeline_events` journal every 2 s
  and the scan/push dedup sets grew one entry per event forever; journal
  scans are now cursor-bounded and the seen-sets capped (issue #183, details
  in [serving-bridge.md](serving-bridge.md#journal-scans-are-bounded-issue-183)).
  Unit scale: per-scan allocation flat ≤ 0.8 MB against a journal growing
  50 k → 400 k rows (was 35.5 → 283.6 MB). **Live re-verification
  2026-07-11:** 97 min at the soak read/apply profile against a 1.37 M-row
  journal — RSS slope **+7.5 MB/h**, plateaued (was ~+370 MB/h monotonic);
  [perf/rss-reverify-183-2026-07-11.md](perf/rss-reverify-183-2026-07-11.md).

## Post-closure operations and future work

The items below are not active engineering backlog for the closing release.
They require a separately authorized acceptance, deployment, or breaking-release
program.

1. **Golden-topology acceptance** — clean-checkout OCI build + submission smoke
   is **PASS**
   ([perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md));
   clean kind + Kubernetes Operator + Helm deployment of the verified image
   on exact HEAD `36ed1ec` is **PASS**
   ([perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md));
   live Iceberg materialization from direct `events.validated` is **PASS**
   at the narrow boundary
   ([perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md));
   full one-event lake-to-serving smoke is **PASS**
   ([perf/full-lake-to-serving-e2e-2026-08-01.md](perf/full-lake-to-serving-e2e-2026-08-01.md));
   and isolated checkpoint restore/replay is **PASS**
   ([perf/checkpoint-restore-replay-2026-08-02.md](perf/checkpoint-restore-replay-2026-08-02.md)).
   Fresh soak/rollback remains open. Historical canary1 is
   **`FAIL_CANARY_CATCHUP_RATE_FLOOR`** in
   [perf/golden-4h-soak-canary-failure-2026-08-02.md](perf/golden-4h-soak-canary-failure-2026-08-02.md)
   (baseline and 2000/2000 delivery passed; exact catch-up failed). The first
   recovery preflight was
   **`BLOCKED_RESOURCE_HEADROOM_BEFORE_SAFE_CUTOVER`**, but a later controlled
   cutover deployed the exact corrected revision-3 pack. Its subsequent
   930-second read-only readiness-baselined checkpoint hold is
   **`RUNTIME_HOLD_PASS`** with completed checkpoints `7675→8614` and failed
   checkpoints `1→1`
   ([perf/ready-baselined-checkpoint-hold-2026-08-03.md](perf/ready-baselined-checkpoint-hold-2026-08-03.md)).
   A later kind residual canary **PASS** unlocked soak traffic
   ([perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md](perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md)).
   Multiple soak identities were then attempted; latest
   `golden-4h-soak-rv-20260807-05` producer completed PASS (`1_440_000`
   delivered, failures `0`) but the soak gate failed closed with
   **`SOAK_FAIL`** on terminal Flink health before dual-mean verify could
   PASS; corrected rollback was **not started** — see
   [perf/golden-4h-soak-05-failure-2026-08-08.md](perf/golden-4h-soak-05-failure-2026-08-08.md).
   Historical revisions 1 and 2 are not rollback targets for the corrected
   runtime; the prepared recovery target is revision 3. Old 4h evidence is
   advisory only.
   Exactly two production-acceptance gates remain overall: (1) fresh
   soak+rollback (readiness-baselined hold `RUNTIME_HOLD_PASS`; kind residual
   canary PASS; latest soak `SOAK_FAIL`; corrected rollback not started;
   combined gate open); (2) external pen-test
   (**`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`** at
   `2026-08-01T17:11:58Z` —
   [operations/external-pentest-evidence-blocker-2026-08-01.md](operations/external-pentest-evidence-blocker-2026-08-01.md);
   evidence/readiness only, not a pen-test; intake not present/unclaimed; all
   seven criteria fail). The npm approval gate is **PASS**
   ([operations/npm-environment-approval-2026-08-03.md](operations/npm-environment-approval-2026-08-03.md)).
   Current tracked evidence leaves the two remaining gates dependent on a
   newly identified soak/rollback run with retained Flink exception evidence,
   or an external pentest owner. Do not
   procure, simulate, or perform a pen-test from docs work.
   Acceptance-scaffold Kafka reproducibility
   debt (kind runtime fixes for `enableServiceLinks` / controller quorum
   voters) is recorded in the Operator evidence and is not a
   production-acceptance claim.
2. **External notes (not extra production-acceptance gates)** — production CDC
   onboarding/credentials, public production-grade benchmark work, and Codecov
   repository activation remain outside those two gates. The pen-test is
   already counted in item 1; the npm approval gate is closed.
3. **P2-6 packaging** — Phases 1-2 landed in 2.1.0 (2026-08-23): the runtime
   imports as `agentflow_runtime`, first-party code is fully cut over, and
   wheels ship a one-file deprecated `src` shim
   ([migration/v2.1.md](migration/v2.1.md)). Remaining Phase 3 (drop the
   shim + `src` top-level) is scheduled for the next **major** release:
   [plans/p2-6-runtime-namespace-migration.md](plans/p2-6-runtime-namespace-migration.md).
4. **Flink-runtime dependency bump** — the pinned `apache-flink==2.3.0` job
   environment holds a `safety` ignore for a non-fixable transitive `pyarrow`
   advisory (isolated to the Flink image, core pins `pyarrow>=17`); retire the
   ignore when the upstream flink/beam chain allows it.

---

*Keep this file to one page. Add a number only after the measurement doc it
links to exists; retired claims move to the [changelog](../CHANGELOG.md).*
