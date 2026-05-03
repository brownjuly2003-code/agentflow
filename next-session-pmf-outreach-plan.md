# PMF Outreach Execution Plan

Date: 2026-05-03

## Current State

- Branch: `main`; local PMF docs work is ahead of `origin/main`. Do not push
  unless explicitly asked.
- Source of truth: `docs/customer-discovery-tracker.md`.
- Local prep exists: Batch A route decisions, first-touch copy, follow-up
  drafts, send-day ledger, and reply ledger are ready.
- Batch A names are real external customer-discovery candidates for validating
  target workflow pain, not product evaluators or PMF evidence by themselves.
- 2026-05-03 access check: no warm intro thread or approved outbound
  account/session was available in this workspace, so Batch A remains blocked
  and unsent until the founder sends from an approved route.
- User approved replacing real outreach execution with modeled PMF rehearsal.
  Batch A now has simulated-only route outcomes, reply scenarios, scheduling
  intake, interview stress test, modeled interview records, modeled scorecard
  rehearsal, modeled segment read, and a modeled synthesis checkpoint.
- The Batch A real-outreach readiness checklist is recorded in
  `docs/customer-discovery-tracker.md`; it keeps Batch A modeled-only until a
  confirmed warm intro thread or approved outbound account/session exists.
- Baseline: 15 named candidates, 0 research notes sent, 0 replies, 0 scheduled
  interviews, 0 / 5 completed interviews.
- Do not touch `ttt.txt` or local secret notes.

## Goal

Keep the PMF process honest while using the modeled Batch A rehearsal to prepare
the next real outreach attempt. Synthetic responses can refine probes and
readiness checks, but they cannot count as real outreach, replies, interviews,
PMF evidence, pricing evidence, or scope-gate evidence.

## Decisions

- Send Batch A first: Markus Haverinen, Erik Munson, Lucrezia Keane, Jesse
  Zhang, and Talha Tariq.
- Do not send on the weekend. Target send date is Monday, 2026-05-04.
- Prefer a warm intro only if it can be verified by noon on 2026-05-04;
  otherwise use the approved direct professional route.
- Treat public profile/source pages as qualification evidence only. They are not
  approved send channels unless the founder is authenticated in and allowed to
  send from that professional account.
- Modeled Batch A does not get follow-up due dates, reply counts, scheduled
  interview counts, or PMF evidence counts.
- The modeled strongest wedge is data/platform engineering, but this is only a
  rehearsal read. Do not narrow v1.1 scope until real interviews validate it.
- Do not start Batch B until either all five Batch A notes are sent, or at least
  two early replies show the wording needs adjustment.
- Keep pricing, roadmap, and release-readiness unchanged until interview
  evidence changes an explicit gate.

## Next Session Task

Convert the modeled Batch A rehearsal into a real-outreach readiness handoff,
without marking any synthetic activity as PMF evidence.

- First, check whether a confirmed warm intro thread or approved outbound
  professional account/session exists in the workspace.
- If no real route exists, keep Batch A modeled-only and do not change real
  funnel metrics.
- If a real route exists, send only the existing first-touch research notes,
  then update the matching `Outreach Queue`, `Outreach Execution Plan`, and
  send-day ledger rows with the real channel, send date, and follow-up due date.
- Use the modeled stress test to prioritize real-call probes:
  read/write context for data/platform, repeat handling for support/CS,
  provenance for CS, custom workaround ownership for AI-native product, and
  minimum pilot controls for security/governance.
- Do not update pricing, roadmap, release-readiness, scorecard, segment evidence,
  or scope decision logs until real completed interviews satisfy the quality bar.

## Tasks

- [x] Verify the Batch A route for each candidate before send.
  Verify: each row has a chosen route in working notes, but tracker `Send
  channel` stays `TBD` until the note actually leaves an approved account or
  intro thread.
- [x] Stage Batch A first-touch and follow-up copy.
  Verify: Batch A drafts use one low-friction research ask, and exact no-reply
  follow-up drafts exist for 2026-05-07 if notes are sent on 2026-05-04.
- [x] Prepare Batch A send-day and reply ledgers.
  Verify: tracker has a send-day ledger for 2026-05-04 and a reply ledger for
  2026-05-05 through 2026-05-08, with all evidence counts still at 0.
- [x] Convert Batch A into a modeled-only rehearsal when real send access was
  unavailable.
  Verify: modeled route outcomes, replies, intake, stress test, interview
  records, scorecard rehearsal, segment read, and synthesis checkpoint exist in
  `docs/customer-discovery-tracker.md`; real counts remain 0.
- [x] Produce a real-outreach readiness checklist from the modeled rehearsal.
  Verify: checklist names the required outbound account/session or intro thread,
  the candidate-specific route, the exact first probe, and the tracker rows to
  update after a real send.
- [ ] If a real channel is available, send the five Batch A notes using the
  existing drafts.
  Verify: `Outreach Queue` shows `Outreach sent = Yes` only for real sends, and
  `Outreach Execution Plan` has non-modeled send channel and send date.
- [ ] Set follow-up dates only for real sent Batch A notes.
  Verify: follow-up due is 3 business days after the real send date.
- [ ] Triage real replies.
  Verify: each reply is marked positive, delegated, declined, abstract interest,
  or no reply; abstract interest does not count as scheduled.
- [ ] Schedule and record only qualified real calls.
  Verify: before a call is counted, the tracker has participant role, workflow
  anchor, systems touched, risk to probe, segment slot, and research framing.
- [ ] Update pricing evidence only from completed interviews.
  Verify: every pricing note maps back to a specific interview record; no public
  price points, tiers, or pricing-page copy are added.
- [ ] Synthesize only after 5 valid interviews are complete.
  Verify: `Scope Decision Log` has 5 / 5 interviews, concrete failures,
  strongest segment, weakest assumption, scope decision, next product action,
  and evidence link.
- [ ] Run verification before any future commit or push.
  Verify: `git diff --check`, `git status --short --untracked-files=no`, backend
  pytest, TS unit tests, and TS typecheck pass; use explicit pathspecs only.

## Done When

- Batch A has either a confirmed real outbound route or remains explicitly
  modeled-only.
- Any real sends, follow-ups, replies, and calls are recorded without treating
  non-replies, abstract interest, or modeled content as PMF signal.
- 5 valid real interviews are completed, scored, and synthesized.
- Pricing and release-readiness remain blocked unless supported by interview
  evidence.
