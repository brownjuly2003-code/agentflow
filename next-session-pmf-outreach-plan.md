# PMF Outreach Execution Plan

Date: 2026-05-03

## Current State

- Branch: `main`; this PMF handoff continuation started from latest pushed
  commit `4d67b7f` (`docs: add modeled product risk implications`). Do not push
  again unless explicitly asked.
- Source of truth: `docs/customer-discovery-tracker.md`.
- Local prep exists: Batch A route decisions, first-touch copy, follow-up
  drafts, send-day ledger, and reply ledger are ready.
- Batch A names are real-world research anchors for modeling target workflow
  pain, not contacted participants, product evaluators, or PMF evidence.
- 2026-05-03 access check: no warm intro thread or approved outbound
  account/session was available in this workspace; this is now historical
  context only because real outreach is retired.
- 2026-05-03 route recheck: workspace markdown still contains no confirmed
  warm intro thread or approved outbound professional account/session for Batch
  A; keep Batch A modeled-only.
- 2026-05-03 permanent synthetic-mode decision: real outreach, real replies,
  scheduled interviews, and completed interviews will not be available for this
  project. Treat the modeled track as the active operating path, while keeping
  evidence count and real funnel metrics at `0`.
- User approved replacing real outreach execution with modeled PMF rehearsal.
  Batch A now has simulated-only route outcomes, synthetic respondent profiles,
  first-reply scenarios, scheduling intake, interview stress test, modeled
  interview records, modeled scorecard rehearsal, modeled segment read, and a
  modeled synthesis checkpoint.
- The Batch A synthetic operating checklist is recorded in
  `docs/customer-discovery-tracker.md`; it keeps Batch A and future batches
  explicitly `Synthetic / Modeled only`.
- Batch B remains unmodeled because expanded Batch A covers all five target
  profiles; model Batch B only if a specific modeled gap appears after a future
  modeled pass.
- The modeled product-risk implication pass is complete. It produced hypotheses
  only, did not update PMF/pricing/roadmap/release-readiness/scope evidence, and
  did not create a specific modeled gap that justifies Batch B.
- The selected modeled deepening pass is complete: one blocked data/platform
  action-safety scenario around an unsafe CRM account-state write. It is
  `Synthetic / Modeled only`, hypothesis only, evidence count `0`, and it does
  not create a specific modeled gap that justifies Batch B.
- Baseline: 15 named candidates, 0 research notes sent, 0 replies, 0 scheduled
  interviews, 0 / 5 completed interviews.
- Do not touch `ttt.txt` or local secret notes.

## Goal

Keep the PMF process honest while using modeled customer discovery as the active
planning surface. Synthetic responses can refine probes, score segment
hypotheses, and guide product-risk questions, but they cannot count as real
outreach, replies, interviews, PMF evidence, pricing evidence, or scope-gate
evidence.

## Decisions

- Model Batch A first: Markus Haverinen, Erik Munson, Lucrezia Keane, Jesse
  Zhang, and Talha Tariq.
- Do not wait for a real send date, warm intro, or outbound account.
- Treat public profile/source pages as qualification evidence only. They are not
  approved send channels or PMF evidence.
- Modeled Batch A does not get follow-up due dates, reply counts, scheduled
  interview counts, or PMF evidence counts.
- The modeled strongest wedge is data/platform engineering, but this is only a
  rehearsal read. Any v1.1 scope change must be labeled `Synthetic / Modeled
  only`.
- Leave modeled Batch B at `0` unless a future pass names a specific uncovered
  workflow or segment gap.
- Keep pricing, roadmap, and release-readiness unchanged as evidence-based
  artifacts; modeled outputs can create planning hypotheses only.

## Next Session Task

Continue the modeled-only PMF handoff without marking any synthetic activity as
PMF evidence.

- First, keep the permanent synthetic-mode decision visible in
  `docs/customer-discovery-tracker.md`.
- Treat the completed Batch A modeled action-safety deepening pass as hypothesis
  only.
- Use modeled Batch A as the active planning surface and keep real funnel
  metrics frozen at `0`.
- Do not send first-touch notes, set real follow-up dates, or create real reply
  rows.
- Do not start Batch B unless a future pass names a specific modeled uncovered
  workflow or segment gap.
- If another deepening pass is needed, choose exactly one minimum-control
  scenario and keep it `Synthetic / Modeled only`.
- Do not update pricing, roadmap, release-readiness, real scorecard, real segment
  evidence, or real scope decision logs from modeled material.

## Tasks

- [x] Verify the Batch A modeled route stance for each candidate.
  Verify: each row has a synthetic route assumption and no real send channel.
- [x] Stage Batch A first-touch and follow-up copy.
  Verify: Batch A drafts use one low-friction research ask, and no-reply
  follow-up drafts are available for modeled no-reply scenarios.
- [x] Prepare Batch A modeled send-day and reply ledgers.
  Verify: tracker has modeled send-day and reply ledgers, with all evidence
  counts still at 0.
- [x] Convert Batch A into a modeled-only rehearsal.
  Verify: modeled route outcomes, replies, intake, stress test, interview
  records, scorecard rehearsal, segment read, and synthesis checkpoint exist in
  `docs/customer-discovery-tracker.md`; real counts remain 0.
- [x] Convert the real-outreach readiness checklist into a synthetic operating
  checklist.
  Verify: checklist names the modeled route stance, the required modeled
  artifacts, the exact first probe, and the modeled tracker rows to update.
- [x] Record permanent synthetic-mode decision.
  Verify: `docs/customer-discovery-tracker.md` says real outreach, real replies,
  scheduled interviews, and completed interviews will not be available; real
  funnel metrics remain frozen at `0`.
- [x] Expand Batch A modeled artifacts from the synthetic workflow.
  Verify: modeled profile, reply simulation, scheduling intake, interview
  record, scorecard rehearsal, segment read, and synthesis all remain
  `Synthetic / Modeled only`.
- [x] Decide whether Batch B needs modeling.
  Verify: start Batch B only if Batch A leaves a specific modeled gap or the
  synthetic read needs another segment pass.
- [x] Draft modeled-only product-risk implications.
  Verify: every implication is labeled as a hypothesis; no pricing, PMF,
  roadmap, release-readiness, or evidence gate is updated.
- [x] Decide whether the product-risk implication pass justifies Batch B.
  Verify: no specific modeled gap was created; Batch B remains at `0`.
- [x] Keep real metrics and evidence ledgers frozen.
  Verify: research notes sent, replies, scheduled interviews, completed
  interviews, and evidence count remain `0`.
- [x] Deepen one modeled action-safety or minimum-control scenario only if
  needed.
  Verify: one data/platform action-safety row was added as `Synthetic / Modeled
  only`, evidence count stayed `0`, and no real evidence surface was updated.
- [ ] Next handoff: decide whether one minimum-control scenario is needed.
  Verify: only proceed if it names a specific modeled gap; otherwise keep Batch
  B at `0` and leave all real evidence surfaces unchanged.
- [x] Run `git diff --check` for the current docs-only pass.
  Verify: whitespace check passes after the tracker and handoff edits.
- [ ] Run verification before any future commit or push.
  Verify: `git diff --check`, `git status --short --untracked-files=no`, backend
  pytest, TS unit tests, and TS typecheck pass; use explicit pathspecs only.

## Done When

- Permanent synthetic mode is recorded in the source-of-truth tracker.
- Batch A and any future Batch B work remain explicitly `Synthetic / Modeled
  only`.
- Real sends, follow-ups, replies, scheduled calls, completed interviews, and
  evidence counts remain `0`.
- Modeled records are scored and synthesized as planning hypotheses only.
- Pricing, PMF, roadmap, release-readiness, segment, and scope evidence remain
  blocked unless the user explicitly creates a separate synthetic-decision doc.

## Next Handoff

Start from `docs/customer-discovery-tracker.md`. Permanent synthetic mode remains
active: real outreach, real replies, scheduled interviews, and completed
interviews will not be available. The latest completed work is one Batch A
modeled data/platform action-safety deepening pass, labeled `Synthetic /
Modeled only`. Treat it as a hypothesis only. Batch B stays at `0` because the
pass found no specific modeled coverage gap. The next useful modeled pass, if
any, is to decide whether one minimum security-control scenario is needed
without changing evidence count, PMF evidence, pricing evidence, roadmap, scope,
or release-readiness.
