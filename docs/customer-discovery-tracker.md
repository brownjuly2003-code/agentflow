# AgentFlow Customer Discovery Tracker

**Date:** 2026-05-01
**Goal:** run 5 real discovery interviews before committing v1.1 product scope
**Script:** [Customer Discovery Questions](customer-discovery-questions.md)
**Research baseline:** [v1.1 Interview Preparation Report](v1-1-interview-prep.md)

This tracker keeps the PMF work operational without marking the PMF gate complete.
Use it after every founder-led interview to record evidence, score the segment,
and decide whether the v1.1 roadmap still fits real customer pain.

## Interview Sample Plan

Target at least 5 independent interviews before changing v1.1 scope.

| Slot | Target profile | Workflow to validate | Source/intro path | Status | Date | Next action |
|------|----------------|----------------------|-------------------|--------|------|-------------|
| 1 | Support/CS engineering lead at a mid-market SaaS company | Agent answers account, order, subscription, or entitlement questions | Warm intro, LinkedIn, or support-agent community | Not scheduled | TBD | Identify 3 teams already piloting support agents |
| 2 | Data/platform engineering lead at a company with multiple operational systems | Internal agent needs fresh entities or metrics across systems | Warm intro, data engineering community, or former colleague path | Not scheduled | TBD | Find teams with schema drift, glue code, or safe serving pain |
| 3 | Ops/revenue operations owner using internal AI workflows | Agent monitors fulfillment, pipeline, or customer state | RevOps/operator community or founder network | Not scheduled | TBD | Validate whether freshness is a buying driver or only a trust symptom |
| 4 | Founder/CTO of an AI-native B2B product | Product agent needs customer or business context from live systems | AI founder network, Product Hunt, or direct peer intro | Not scheduled | TBD | Test startup willingness to pay versus build-it-yourself |
| 5 | Security-conscious engineering buyer | Agent access is blocked by governance, permissions, or auditability | Security/platform leader referral or enterprise buyer intro | Not scheduled | TBD | Check whether governance is first wedge or later enterprise requirement |

## Outreach Queue

Use this as a working list before calls are scheduled. Keep the request framed as
research, not a product pitch.

| Candidate/team | Target slot | Source | Outreach sent | Follow-up due | Outcome |
|----------------|-------------|--------|---------------|---------------|---------|
| TBD | 1 | TBD | No | TBD | Not contacted |
| TBD | 2 | TBD | No | TBD | Not contacted |
| TBD | 3 | TBD | No | TBD | Not contacted |
| TBD | 4 | TBD | No | TBD | Not contacted |
| TBD | 5 | TBD | No | TBD | Not contacted |

## Candidate Qualification

Prioritize candidates who meet at least two of these signals:

- They already use or pilot AI agents in a business workflow.
- The workflow touches operational data such as accounts, orders, subscriptions,
  entitlements, inventory, customer state, or pipeline state.
- A wrong answer would create user-visible risk, support load, financial impact,
  or trust loss.
- The team owns custom glue, curated views, internal tools, or security review
  work around agent data access.
- A technical or operational owner can describe what a 30-60 day pilot would
  need to prove.

Deprioritize candidates when the use case is only generic document retrieval,
one-off analytics, personal productivity, or broad AI curiosity without a
specific operational workflow.

## Outreach Templates

### Warm intro request

```text
Could you introduce me to someone on your team who has dealt with getting live
business data into AI agents or internal AI workflows?

I'm doing 30-minute research calls, not pitching a product. I want to understand
where the current data path breaks, who owns the workaround, and what would make
the problem worth solving.
```

### Direct research note

```text
Hi [Name] - I'm researching how teams get live operational data into AI agents.
I'm especially interested in cases where stale, missing, split, or unsafe data
caused a wrong answer or blocked a workflow.

Would you be open to a 30-minute research call? This is not a sales call. I'm
trying to understand what teams have already tried, what breaks in practice, and
what would need to be true for a better approach to matter.
```

### Follow-up

```text
Quick follow-up on this. The most useful input would be one concrete example:
the last time an AI workflow gave a wrong, stale, incomplete, or unsafe answer
because the business data path was off.

If that has happened on your team, I'd value 30 minutes to understand the
workflow and what happened next.
```

## Interview Prep Checklist

Before each call:

- Confirm the participant knows this is research, not a sales call.
- Keep the first five minutes focused on one recent concrete failure or near-miss.
- Do not mention AgentFlow, MCP, LangChain, or real-time data until the optional concept test.
- Capture one exact quote about trust, workflow risk, maintenance burden, or governance.
- Fill the scorecard within one hour while the details are still fresh.

## Per-Interview Record

Copy this block after each call.

```text
Interview:
Date:
Role:
Company stage/size:
Workflow discussed:
Agent stack:
Last concrete failure:
Systems involved:
Current data path:
Freshness requirement by workflow:
Main blocker today:
Current workaround:
Security/governance concern:
Mentioned alternatives:
Strongest buying signal:
Strongest rejection signal:
Exact quote worth keeping:
Follow-up needed:
```

## Scorecard

Score each interview from `0` to `3` using the rubric in
[Customer Discovery Questions](customer-discovery-questions.md#post-call-scoring-template).

| Slot | Pain severity | Freshness criticality | Glue burden | Ownership clarity | Pilot readiness | Budget/WTP signal | Governance pressure | Total |
|------|---------------|-----------------------|-------------|-------------------|-----------------|-------------------|---------------------|-------|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 5 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## Decision Gates After 5 Interviews

Proceed with the current v1.1 direction only if the interview batch shows:

- At least 3 interviews include a concrete recent failure or near-miss.
- At least 3 interviews score `2` or higher on glue burden, ownership clarity,
  or pilot readiness.
- At least 2 interviews show a credible 30-60 day pilot path.
- Existing vendor or internal-build alternatives are not clearly "good enough"
  for the target workflow.

Change the roadmap before implementation if:

- Most teams describe only document retrieval or generic NL-to-SQL needs.
- Freshness/trust is not tied to a real workflow consequence.
- Buyers value protocol support but do not care about typed contracts,
  provenance, or safe serving boundaries.
- Governance dominates every promising conversation before a lightweight pilot
  can be defined.

## Synthesis Template

After 5 interviews, summarize:

- strongest validated pain:
- weakest assumption:
- best-fit ICP segment:
- strongest exact quote:
- most common alternative:
- most credible pilot shape:
- v1.1 scope change required:
- confidence: Low / Medium / High
