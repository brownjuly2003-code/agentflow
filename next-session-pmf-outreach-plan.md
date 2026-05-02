# PMF Outreach Execution Plan

Date: 2026-05-03

## Current State

- Branch: `main`; latest pushed commit: `94e5c40 docs: define pmf outreach execution`.
- Source of truth: `docs/customer-discovery-tracker.md`.
- Local prep exists: Batch A route decisions, first-touch copy, follow-up
  drafts, send-day ledger, and reply ledger are ready.
- Batch A names are real external customer-discovery candidates for validating
  target workflow pain, not product evaluators or PMF evidence by themselves.
- 2026-05-03 access check: no warm intro thread or approved outbound
  account/session was available in this workspace, so Batch A remains blocked
  and unsent until the founder sends from an approved route.
- Baseline: 15 named candidates, 0 research notes sent, 0 replies, 0 scheduled
  interviews, 0 / 5 completed interviews.
- Do not touch `ttt.txt` or local secret notes.
- Do not push unless explicitly asked.

## Goal

Move from prepared PMF outreach assets to real evidence: send Batch A, track
reply quality, schedule only qualified discovery calls, and keep pricing and
release decisions blocked until 5 valid interviews are completed and scored.

## Decisions

- Send Batch A first: Markus Haverinen, Erik Munson, Lucrezia Keane, Jesse
  Zhang, and Talha Tariq.
- Do not send on the weekend. Target send date is Monday, 2026-05-04.
- Prefer a warm intro only if it can be verified by noon on 2026-05-04;
  otherwise use the approved direct professional route.
- Treat public profile/source pages as qualification evidence only. They are not
  approved send channels unless the founder is authenticated in and allowed to
  send from that professional account.
- For Batch A sent on 2026-05-04, set follow-up due to 2026-05-07.
- Do not start Batch B until either all five Batch A notes are sent, or at least
  two early replies show the wording needs adjustment.
- Keep pricing, roadmap, and release-readiness unchanged until interview
  evidence changes an explicit gate.

## Next Session Task

On Monday, 2026-05-04, execute Batch A outreach without changing PMF evidence
counts until a real send/reply/schedule event occurs.

- Before noon: check whether any warm intro route is actually available.
- If no warm intro is confirmed for a candidate, use the chosen direct
  professional route from `Batch A Route Decisions`, but only from an approved
  outbound account/channel.
- After each note is sent, update both the `Outreach Queue` row and the
  `Outreach Execution Plan` row with the real send channel, send date, and
  follow-up due date.
- Set follow-up due to 2026-05-07 for any note sent on 2026-05-04.
- Do not update `Batch Funnel Metrics` until all five Batch A rows are
  reconciled.

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
- [ ] Send the five Batch A notes on 2026-05-04 using the existing drafts.
  Verify: `Outreach Queue` shows `Outreach sent = Yes` for all five, and
  `Outreach Execution Plan` has non-`TBD` send channel and send date.
- [ ] Set follow-up dates for sent Batch A notes.
  Verify: all five Batch A rows have `Follow-up due = 2026-05-07`, unless a note
  is sent on a different date, in which case use 3 business days after send.
- [ ] Triage replies daily from 2026-05-05 through 2026-05-08.
  Verify: each reply is marked positive, delegated, declined, abstract interest,
  or no reply; abstract interest does not count as scheduled.
- [ ] Send one follow-up on 2026-05-07 to any Batch A candidate with no reply.
  Verify: follow-up is recorded; after the follow-up window, no-reply rows are
  marked as no reply and not counted as product signal.
- [ ] Schedule only qualified calls.
  Verify: before a call is counted as scheduled, the tracker has participant
  role, workflow anchor, systems touched, risk to probe, segment slot, and
  research framing.
- [ ] Record every completed call within one hour.
  Verify: a `Per-Interview Record` block is filled, the scorecard is updated,
  and the call counts only if it passes the `Interview Quality Bar`.
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

- Batch A is sent and reconciled.
- Follow-ups and replies are recorded without treating non-replies as PMF
  signal.
- 5 valid interviews are completed, scored, and synthesized.
- Pricing and release-readiness remain blocked unless supported by interview
  evidence.
