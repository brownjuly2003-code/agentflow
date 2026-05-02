# AgentFlow Customer Discovery Tracker

**Date:** 2026-05-01
**Goal:** run 5 real discovery interviews before committing v1.1 product scope
**Script:** [Customer Discovery Questions](customer-discovery-questions.md)
**Research baseline:** [v1.1 Interview Preparation Report](v1-1-interview-prep.md)

This tracker keeps the PMF work operational without marking the PMF gate complete.
Use it after every founder-led interview to record evidence, score the segment,
and decide whether the v1.1 roadmap still fits real customer pain.

## Current Operating Step

Batch 1 sourcing is complete. The next operating step is sending the first
research notes and tracking replies, not changing roadmap, pricing, or
positioning.

- Keep the 15 named candidates below as the first sourcing baseline.
- Send the first 10 research notes across all 5 target profiles.
- Schedule no more than 2 interviews from the same profile until all 5 slots have
  at least one credible candidate.
- Do not change v1.1 scope, pricing, or positioning until the first 5 interviews
  are scored.

## Interview Sample Plan

Target at least 5 independent interviews before changing v1.1 scope.

| Slot | Target profile | Workflow to validate | Source/intro path | Status | Date | Next action |
|------|----------------|----------------------|-------------------|--------|------|-------------|
| 1 | Support/CS engineering lead at a mid-market SaaS company | Agent answers account, order, subscription, or entitlement questions | Warm intro, LinkedIn, or support-agent community | Not scheduled | TBD | Identify 3 teams already piloting support agents |
| 2 | Data/platform engineering lead at a company with multiple operational systems | Internal agent needs fresh entities or metrics across systems | Warm intro, data engineering community, or former colleague path | Not scheduled | TBD | Find teams with schema drift, glue code, or safe serving pain |
| 3 | Ops/revenue operations owner using internal AI workflows | Agent monitors fulfillment, pipeline, or customer state | RevOps/operator community or founder network | Not scheduled | TBD | Validate whether freshness is a buying driver or only a trust symptom |
| 4 | Founder/CTO of an AI-native B2B product | Product agent needs customer or business context from live systems | AI founder network, Product Hunt, or direct peer intro | Not scheduled | TBD | Test startup willingness to pay versus build-it-yourself |
| 5 | Security-conscious engineering buyer | Agent access is blocked by governance, permissions, or auditability | Security/platform leader referral or enterprise buyer intro | Not scheduled | TBD | Check whether governance is first wedge or later enterprise requirement |

## Sourcing Worklist

Fill this before sending outreach. A candidate is credible only if there is a
specific reason to believe they have touched agent data access, support
automation, platform data contracts, internal AI tools, or security review for
AI workflows.

| Target slot | Minimum candidate count | Best first source | Backup source | Qualification note |
|-------------|-------------------------|-------------------|---------------|--------------------|
| 1 | 3 | Warm support/CS engineering intros | Support tooling communities | Must have live account/order/subscription context |
| 2 | 3 | Data/platform engineering intros | Data engineering communities | Must own schema drift, data contracts, or internal APIs |
| 3 | 3 | RevOps/operator referrals | Founder/customer network | Must own a workflow where stale state affects operations |
| 4 | 3 | AI-native B2B founder peers | Builder communities | Must have built or evaluated product-facing agents |
| 5 | 3 | Security/platform leader referrals | Enterprise buyer intros | Must know what blocks agent access approval |

## Candidate Research Batch 1

These candidates are sourced from public customer stories, company profiles, or
reported interviews. Public sources are evidence of relevance only; do not add
private contact details here.

| Target slot | Candidate/team | Public source | Qualification reason | Outreach priority |
|-------------|----------------|---------------|----------------------|-------------------|
| 1 | Markus Haverinen, Head of Support Operations, Frends | [Fin customer story](https://fin.ai/customers/frends) | Operates a human+AI support workflow where Fin handles most support requests; likely to know what live support context and escalation controls require. | Batch 1 |
| 1 | Darren Hockley, Support and Technology Operations Director, Dotdigital | [Fin AI Agent Blueprint](https://fin.ai/blueprint/service/scaling-ai-agents/org-and-system-design) | Publicly described rollout proof for 2,800 AI resolutions per month; likely to discuss support ownership, workflow confidence, and quality loops. | Batch 1 |
| 1 | Natalie Onions, VP of Customer Service, Customer.io | [My AskAI customer proof](https://myaskai.com/ai-agent-integration/intercom) | B2B SaaS support leader replacing Zendesk AI and saving team time; strong fit for account/subscription support automation questions. | Batch 2 |
| 2 | Erik Munson, Founding Engineer, Day AI | [Materialize case study](https://materialize.com/customer-stories/day-ai/) | Built live CRM context for agents from multiple upstream sources, permissions, and human/AI writes; direct fit for freshness and canonical entity questions. | Batch 1 |
| 2 | James Luo, Head of Data and AI, BGL | [ZenML LLMOps case study](https://www.zenml.io/llmops-database/ai-agent-for-self-service-business-intelligence-with-text-to-sql) | Owns a regulated self-service analytics agent backed by Athena/dbt and identity-based controls; strong fit for data foundation and governance questions. | Batch 1 |
| 2 | Vikram Chauhan, Head of Data Engineering, Koheisan | [Streamkap customer proof](https://streamkap.com/) | Led near-real-time pipeline migration where limited freshness and support burden were explicit pain points; useful for CDC/freshness validation. | Batch 2 |
| 3 | Lucrezia Keane, Global SVP of Customer Success, GWI | [Hook customer proof](https://hook.co/) | Uses AI agents over product, revenue, meeting, and support context for scaled CS; fits stale customer-state and renewal-risk workflow validation. | Batch 1 |
| 3 | Nicole Looker, Director of Revenue Operations, Rebuy Engine | [Sweep customer page](https://www.sweep.io/customers) | RevOps owner using AI-powered Salesforce documentation to reduce configuration discovery time; fits CRM workflow and operational-data ownership questions. | Batch 1 |
| 3 | Jay Mahoney, Principal Revenue Operations Manager, Deputy | [Sweep customer page](https://www.sweep.io/customers) | Publicly cites asking an AI agent what is happening in Salesforce Flow; fit for brittle workflow, data lineage, and admin burden questions. | Batch 2 |
| 4 | Jesse Zhang, Co-founder and CEO, Decagon | [OpenAI customer story](https://openai.com/index/decagon/) | Builds production customer-support agents that capture customer business logic and act across client workflows; strong concept-test target. | Batch 1 |
| 4 | Marty Kausas, Co-founder and CEO, Pylon | [Y Combinator company profile](https://www.ycombinator.com/companies/pylon-2) | Builds B2B customer support platform across Slack, Teams, email, portals, and workflows; likely to know customer-context and post-sales agent constraints. | Batch 1 |
| 4 | Bret Taylor or Clay Bavor, Co-founders, Sierra | [TechCrunch launch coverage](https://techcrunch.com/2024/02/13/bret-taylors-new-company-aims-to-connect-conversational-ai-to-enterprise-workflows/) | Building AI customer-service agents that connect to enterprise systems and take actions such as subscription or order changes. | Batch 2 |
| 5 | Talha Tariq, CISO, Vercel | [ITPro 1Password coverage](https://www.itpro.com/security/1password-unified-access-agent-identity-security) | Publicly frames agentic coding and credentials as a developer-workflow security problem; strong fit for scoped credential and audit questions. | Batch 1 |
| 5 | Haider Pasha, EMEA CISO, Palo Alto Networks | [ITPro agentic AI security interview](https://www.itpro.com/security/agentic-ai-poses-major-challenge-for-security-professionals-says-palo-alto-networks-emea-ciso) | Discusses runtime controls, API/MCP/SDK dependencies, privileges, and prompt/tool misuse for agents at scale. | Batch 1 |
| 5 | Stephen McDermid, EMEA CISO, Okta | [TechRadar Okta interview](https://www.techradar.com/pro/security/everybodys-under-pressure-to-do-more-with-less-why-okta-says-you-need-an-ai-agent-governance-strategy-and-sooner-rather-than-later) | Focuses on non-human identity, least privilege, agent permissions, and audit trails; strong fit for enterprise approval blockers. | Batch 2 |

## Outreach Queue

Use this as a working list before calls are scheduled. Keep the request framed as
research, not a product pitch.

| Candidate/team | Target slot | Source | Outreach sent | Follow-up due | Outcome |
|----------------|-------------|--------|---------------|---------------|---------|
| Markus Haverinen, Frends | 1 | Fin customer story | No | TBD after first note | Not contacted |
| Darren Hockley, Dotdigital | 1 | Fin AI Agent Blueprint | No | TBD after first note | Not contacted |
| Erik Munson, Day AI | 2 | Materialize case study | No | TBD after first note | Not contacted |
| James Luo, BGL | 2 | ZenML LLMOps case study | No | TBD after first note | Not contacted |
| Lucrezia Keane, GWI | 3 | Hook customer proof | No | TBD after first note | Not contacted |
| Nicole Looker, Rebuy Engine | 3 | Sweep customer page | No | TBD after first note | Not contacted |
| Jesse Zhang, Decagon | 4 | OpenAI customer story | No | TBD after first note | Not contacted |
| Marty Kausas, Pylon | 4 | Y Combinator company profile | No | TBD after first note | Not contacted |
| Talha Tariq, Vercel | 5 | ITPro 1Password coverage | No | TBD after first note | Not contacted |
| Haider Pasha, Palo Alto Networks | 5 | ITPro agentic AI security interview | No | TBD after first note | Not contacted |

## Outreach Operating Rules

- Send notes in small batches of 5 so the wording can be adjusted after early
  replies.
- Follow up once after 3 business days unless the person already declined.
- Prefer a warm intro over a cold note when both are available.
- Record the reason each candidate qualified before marking outreach sent.
- Treat non-replies as source-quality signal, not product validation.

## Batch Funnel Metrics

Update this after each outreach batch. The goal is to identify where the PMF
process is blocked before interpreting the interviews.

| Metric | Target before batch review | Current | Interpretation |
|--------|----------------------------|---------|----------------|
| Named candidates sourced | 15 | 15 | Initial sourcing target met; next constraint is outreach execution and reply quality |
| Qualified candidates | 10 | 15 | All 15 have a public signal tied to agent data access, support automation, data contracts, operational AI, or security review |
| Research notes sent | 10 | 0 | Below target means execution is blocked before market signal |
| Replies received | 3 | 0 | Low replies suggest weak source quality, framing, or timing |
| Interviews scheduled | 5 | 0 | Low scheduling after replies suggests weak pain relevance |
| Interviews completed | 5 | 0 | Do not synthesize the batch before this reaches 5 |

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

## Interview Quality Bar

Count an interview toward the 5-call batch only if it produces enough evidence
to score the segment.

| Requirement | Counts as valid | Does not count |
|-------------|-----------------|----------------|
| Concrete workflow | A named agent or AI workflow with operational data dependency | Generic AI interest or document retrieval only |
| Current workaround | Specific data path, glue code, internal tool, manual process, or vendor | "We would probably connect an API" |
| Failure or near-miss | Wrong, stale, incomplete, unsafe, blocked, or distrusted answer | Abstract concern with no incident or workflow |
| Owner | Role or team that owns the workaround or approval path | No clear owner after probing |
| Next-step signal | Pilot condition, rejection reason, budget path, or strong "not now" | Polite interest with no concrete consequence |

If a call misses two or more requirements, keep the notes but replace the slot
with a stronger candidate before synthesizing the batch.

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

## Segment Evidence Matrix

Use this after each completed interview to keep segment-level evidence separate.
Do not average all interviews together if one segment is clearly stronger.

| Segment | Concrete failure count | Strong buying signals | Strong rejection signals | Segment read |
|---------|------------------------|-----------------------|--------------------------|--------------|
| Support/CS engineering | 0 | TBD | TBD | TBD |
| Data/platform engineering | 0 | TBD | TBD | TBD |
| Ops/revops | 0 | TBD | TBD | TBD |
| AI-native product | 0 | TBD | TBD | TBD |
| Security/governance | 0 | TBD | TBD | TBD |

## Post-Call Follow-up

Send this only after the call is complete. Do not use it as a sales sequence.

```text
Thanks again for taking the time. The most useful thing I heard was [specific
workflow/pain in their words].

If I understood correctly, the open question is whether [current workaround or
risk] is painful enough to justify a focused pilot. I'll compare this with the
other research calls before making any roadmap decisions.

If I missed or misread anything, please correct me.
```

## Batch Synthesis Workflow

After all 5 interviews are recorded:

1. Copy the strongest exact quote from each interview into the synthesis template.
2. Count how many calls included a concrete recent failure or near-miss.
3. Count how many calls scored `2` or higher for glue burden, ownership clarity,
   pilot readiness, budget/WTP signal, or governance pressure.
4. Group the calls by workflow type: support/CS, data/platform, ops/revops,
   AI-native product, security/governance.
5. Compare the strongest segment against the decision gates below.
6. Decide whether v1.1 scope stays intact, narrows, or pauses for more discovery.

## Scope Decision Log

Fill this only after the 5-interview batch is complete.

| Decision | Result |
|----------|--------|
| Batch date range | TBD |
| Interviews completed | 0 / 5 |
| Concrete failures or near-misses | TBD |
| Strongest segment | TBD |
| Weakest assumption | TBD |
| Scope decision | TBD |
| Next product action | TBD |
| Evidence link | TBD |

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

## Batch Review Outcomes

Pick exactly one outcome after the first valid 5-interview batch.

| Outcome | When to choose it | Next action |
|---------|-------------------|-------------|
| Continue v1.1 direction | Decision gates pass and one segment is clearly strongest | Write a narrow v1.1 PRD for that segment |
| Narrow the wedge | Pain is real but only one workflow or buyer cares | Rewrite scope around that workflow before building |
| Run another discovery batch | Evidence is mixed but at least two interviews are promising | Source 10 more candidates in the strongest segment |
| Pause product work | Interviews stay abstract, low-pain, or ownerless | Do not build v1.1 features until a stronger pain is found |

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
