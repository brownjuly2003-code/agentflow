# AgentFlow Customer Discovery Tracker

**Date:** 2026-05-01
**Goal:** run a synthetic/modelled discovery batch before committing v1.1 product scope
**Script:** [Customer Discovery Questions](customer-discovery-questions.md)
**Research baseline:** [v1.1 Interview Preparation Report](v1-1-interview-prep.md)

This tracker keeps the PMF work operational in permanent `Synthetic / Modeled
only` mode. Use it to record modelled assumptions, score synthetic segment
rehearsals, and decide which v1.1 risks need product judgment. It does not mark
the PMF gate complete.

The named people below are real-world research anchors used to model plausible
customer-discovery scenarios from public context. They are not contacted
participants, product evaluators, or PMF evidence sources.

Modeling override, 2026-05-03: Batch A is now a simulated customer-discovery
exercise because no approved outbound account/session or confirmed warm intro
thread is available in the workspace. Simulated sends, replies, scheduling
intake, and modeled workflow details are planning inputs only. They do not count
as real outreach, replies, interviews, PMF evidence, or scope-gate evidence.

Permanent synthetic-mode decision, 2026-05-03: real outreach, real replies,
scheduled interviews, completed interviews, and other real customer-discovery
data will not be available for this project. All customer-discovery work in this
tracker is therefore `Synthetic / Modeled only`. Keep real funnel metrics frozen
at `0`, keep evidence counts at `0`, and use the modeled sections as the active
planning surface.

## Current Operating Step

Batch 1 sourcing is complete. The current operating step is using the modeled
Batch A action-safety and minimum security-control passes as hypotheses only.
Batch B remains unmodeled unless a specific modeled gap appears. Do not wait
for real access or convert synthetic outputs into real evidence.

- Keep the 15 named candidates below as the first sourcing baseline.
- Keep all real funnel metrics at 0 because no real sends or interviews will
  occur.
- Use Batch A and Batch B simulations to refine the interview script, triage
  criteria, source-quality assumptions, and product-risk questions.
- Model no more than 2 interview records from the same profile until all 5 slots
  have at least one modeled candidate.
- Do not describe modeled outputs as PMF evidence, pricing evidence, or customer
  validation.

## Interview Sample Plan

Target at least 5 independent modeled interview records before using this
tracker for v1.1 scope judgment.

| Slot | Target profile | Workflow to model | Source context | Status | Date | Next action |
|------|----------------|----------------------|-------------------|--------|------|-------------|
| 1 | Support/CS engineering lead at a mid-market SaaS company | Agent answers account, order, subscription, or entitlement questions | Public support-agent proof | Modeled only | TBD - modeled | Model 3 teams already piloting support agents |
| 2 | Data/platform engineering lead at a company with multiple operational systems | Internal agent needs fresh entities or metrics across systems | Public data/platform proof | Modeled only | TBD - modeled | Model teams with schema drift, glue code, or safe serving pain |
| 3 | Ops/revenue operations owner using internal AI workflows | Agent monitors fulfillment, pipeline, or customer state | Public RevOps/operator proof | Modeled only | TBD - modeled | Model whether freshness is a buying driver or only a trust symptom |
| 4 | Founder/CTO of an AI-native B2B product | Product agent needs customer or business context from live systems | Public AI founder/product proof | Modeled only | TBD - modeled | Model startup willingness to pay versus build-it-yourself |
| 5 | Security-conscious engineering buyer | Agent access is blocked by governance, permissions, or auditability | Public security/platform proof | Modeled only | TBD - modeled | Model whether governance is first wedge or later enterprise requirement |

## Sourcing Worklist

Fill this before modeling a candidate. A candidate is a credible modeling anchor
only if there is a specific public reason to believe they have touched agent
data access, support automation, platform data contracts, internal AI tools, or
security review for AI workflows.

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
| 5 | Talha Tariq, CTO of Security, Vercel | [Vercel announcement](https://vercel.com/blog/talha-tariq-joins-vercel-as-cto-security) and [ITPro 1Password coverage](https://www.itpro.com/security/1password-unified-access-agent-identity-security) | Publicly frames AI security, agentic coding, and credentials as developer-workflow security problems; strong fit for scoped credential and audit questions. | Batch 1 |
| 5 | Haider Pasha, EMEA CISO, Palo Alto Networks | [ITPro agentic AI security interview](https://www.itpro.com/security/agentic-ai-poses-major-challenge-for-security-professionals-says-palo-alto-networks-emea-ciso) | Discusses runtime controls, API/MCP/SDK dependencies, privileges, and prompt/tool misuse for agents at scale. | Batch 1 |
| 5 | Stephen McDermid, EMEA CISO, Okta | [TechRadar Okta interview](https://www.techradar.com/pro/security/everybodys-under-pressure-to-do-more-with-less-why-okta-says-you-need-an-ai-agent-governance-strategy-and-sooner-rather-than-later) | Focuses on non-human identity, least privilege, agent permissions, and audit trails; strong fit for enterprise approval blockers. | Batch 2 |

## Outreach Queue

Use this as a working list before calls are scheduled. Keep the request framed as
research, not a product pitch.

| Candidate/team | Target slot | Source | Outreach sent | Follow-up due | Outcome |
|----------------|-------------|--------|---------------|---------------|---------|
| Markus Haverinen, Frends | 1 | Fin customer story | No - simulated only | N/A - modeled | Modeled scenario / no real contact |
| Darren Hockley, Dotdigital | 1 | Fin AI Agent Blueprint | No - not modeled yet | N/A - modeled | Not modeled |
| Erik Munson, Day AI | 2 | Materialize case study | No - simulated only | N/A - modeled | Modeled scenario / no real contact |
| James Luo, BGL | 2 | ZenML LLMOps case study | No - not modeled yet | N/A - modeled | Not modeled |
| Lucrezia Keane, GWI | 3 | Hook customer proof | No - simulated only | N/A - modeled | Modeled scenario / no real contact |
| Nicole Looker, Rebuy Engine | 3 | Sweep customer page | No - not modeled yet | N/A - modeled | Not modeled |
| Jesse Zhang, Decagon | 4 | OpenAI customer story | No - simulated only | N/A - modeled | Modeled scenario / no real contact |
| Marty Kausas, Pylon | 4 | Y Combinator company profile | No - not modeled yet | N/A - modeled | Not modeled |
| Talha Tariq, Vercel | 5 | ITPro 1Password coverage | No - simulated only | N/A - modeled | Modeled scenario / no real contact |
| Haider Pasha, Palo Alto Networks | 5 | ITPro agentic AI security interview | No - not modeled yet | N/A - modeled | Not modeled |

## First 10 Outreach Drafts

Use these as first-touch research note drafts for modeled reply generation only.
Do not mark `Outreach sent` as `Yes`; real sends will not occur.
For simulation, keep `Outreach sent` explicitly marked as simulated only.

### Markus Haverinen, Frends

- Target slot: 1
- Qualification hook: operates a human+AI support workflow where Fin handles
  most support requests.
- Subject: `support coverage`

```text
Hi Markus - I read the Frends story about Fin being involved in nearly every
support conversation while keeping human control available.

I'm researching what changes after the first rollout works: stale context,
handoff boundaries, and quality loops.

Would you be open to a short research exchange on one recent case where context
or escalation quality mattered? Even a one-line pointer would help.
```

Follow-up angle: ask how "plug-and-play" changed once support workflows,
customer questions, or escalation rules evolved.

### Darren Hockley, Dotdigital

- Target slot: 1
- Qualification hook: built internal confidence using real customer
  conversations and AI resolution numbers.
- Subject: `ai ownership`

```text
Hi Darren - I saw your comments in the Fin Blueprint about building internal
confidence with real customer conversations and then backing it up with
resolution numbers.

I'm researching what changes after that confidence moment: who owns AI
performance, QA, escalation criteria, and fixes when answers drift.

I'm especially interested in the operating model behind trust, not the business
case for AI.

Would you be open to a short research conversation about one case where a
support AI answer was almost right, but needed better context or review?
```

Follow-up angle: ask what evidence now catches failure modes after the original
stakeholder proof worked.

### Erik Munson, Day AI

- Target slot: 2
- Qualification hook: built live CRM context from upstream sources,
  permissions, and human/AI writes.
- Subject: `live context`

```text
Hi Erik - I read the Materialize write-up on Day AI's live CRM context and the
distinction between fast queries and data that feels live and mutable.

I'm researching what breaks first when agents become both readers and writers:
freshness, permissions, canonicalization, explainability, or load.

Would you be open to a short research exchange on one hard case where raw
operational truth had to become trustworthy agent context?
```

Follow-up angle: ask about "time to confident action" and the worst
pre-production tradeoff.

### James Luo, BGL

- Target slot: 2
- Qualification hook: owns a regulated self-service analytics agent backed by a
  deterministic data foundation and identity controls.
- Subject: `data foundation`

```text
Hi James - I read the BGL case study on the self-service BI agent and your point
that teams can't skip the data platform and expect the agent to solve all
complexity.

I'm researching where production analytics agents need deterministic data
foundations, permissions, and validation before business users can trust the
answer.

The Athena/dbt foundation, identity controls, and SQL validation are exactly the
boundary I'm trying to understand from teams that have shipped this in a
regulated environment.

Would you be open to a short research call about one example where accuracy,
governance, or query safety shaped the agent design?
```

Follow-up angle: ask how BGL decides what belongs in dbt/analytic tables versus
agent-side domain context.

### Lucrezia Keane, GWI

- Target slot: 3
- Qualification hook: uses AI agents over product, revenue, meeting, and
  support context for scaled customer success.
- Subject: `scaled cs`

```text
Hi Lucrezia - I saw the Hook/GWI story about scaling CS while improving
engagement and GRR in a scaled segment.

I'm researching how CS leaders decide when AI account intelligence is reliable
enough to influence prioritization, renewal risk, and next-best actions.

Would you be open to a short research exchange on one moment where
customer-state quality affected a CS action or renewal-risk call?
```

Follow-up angle: ask which account signals CSMs trusted, ignored, or overrode in
the scaled segment.

### Nicole Looker, Rebuy Engine

- Target slot: 3
- Qualification hook: RevOps owner using AI-powered Salesforce documentation to
  reduce configuration discovery time.
- Subject: `salesforce context`

```text
Hi Nicole - I saw Rebuy's Sweep story around using AI-powered Salesforce
documentation to reduce time spent understanding configuration.

I'm researching how RevOps teams keep AI-assisted workflows grounded in the
actual current state of Salesforce, especially when Flows, fields, ownership,
and pipeline logic change.

I'd value hearing where documentation stops being enough and someone needs
fresher operational context or lineage.

Would you be open to a 30-minute research conversation? Not pitching anything;
just trying to understand what breaks in practice.
```

Follow-up angle: ask for one recent Salesforce config or Flow change where
documentation, lineage, or AI-assisted discovery lagged behind reality.

### Jesse Zhang, Decagon

- Target slot: 4
- Qualification hook: builds production customer-support agents that capture
  customer business logic and act across client workflows.
- Subject: `workflow context`

```text
Hi Jesse - I read OpenAI's Decagon story. What stood out was the focus on
capturing each customer's business logic, not just answering support questions.

I'm researching where production support agents still hit limits around fresh
state, permissions, escalation boundaries, or customer-specific exceptions.

Would you be open to a short research exchange on one case where workflow
context forced a custom workaround?
```

Follow-up angle: ask about one case where customer-specific business logic,
stale state, or incomplete permissions forced a custom workaround.

### Marty Kausas, Pylon

- Target slot: 4
- Qualification hook: builds B2B customer support workflows across Slack,
  Teams, email, portals, and post-sales channels.
- Subject: `post-sales context`

```text
Hi Marty - I saw Pylon's work across Slack, Teams, email, portals, and post-sales
workflows.

I'm researching how B2B support teams get AI workflows enough customer context to
answer or act without creating support risk.

In B2B support, the hard part seems less like retrieval and more like knowing
account state, entitlement, ownership, and the right escalation path in the
moment.

Would you be open to a 30-minute research conversation about what breaks when
that context is stale or split? Not pitching anything; I'm trying to understand
the operational edges from people building in this category.
```

Follow-up angle: ask which support channel creates the hardest context problem
and what data must be live before an agent can act.

### Talha Tariq, Vercel

- Target slot: 5
- Qualification hook: frames agentic coding and credentials as a
  developer-workflow security problem.
- Subject: `agent credentials`

```text
Hi Talha - I read Vercel's CTO of Security announcement and your comments in
ITPro around agentic coding changing how credentials and developer workflows
need to be secured.

I'm researching where security teams draw the line between useful agent access
and unacceptable credential, privilege, or audit risk.

Would you be open to a short research exchange on what blocks approval when an
engineering team wants an agent to use live credentials or APIs?
```

Follow-up angle: ask what blocks approval first when an engineering team wants
an agent to use API credentials or secrets.

### Haider Pasha, Palo Alto Networks

- Target slot: 5
- Qualification hook: discusses runtime controls, API/MCP/SDK dependencies,
  privileges, and prompt/tool misuse for agents at scale.
- Subject: `agent controls`

```text
Hi Haider - I read your ITPro interview on agentic AI and the security challenge
around runtime controls, dependencies, privileges, and prompt/tool misuse.

I'm researching how security leaders decide whether an AI agent should be
allowed to call tools or APIs in a live business workflow.

The area I'm trying to understand is what blocks approval first: identity,
privilege scope, auditability, runtime monitoring, or the inability to predict
tool behavior.

Would you be open to a 30-minute research conversation? Not pitching anything;
I'm trying to learn what practical controls matter before agent workflows can
scale.
```

Follow-up angle: ask which single control would turn a hard no into a limited
pilot.

## Modeled Outreach Operating Rules

- Model notes in small batches of 5 so the wording can be stress-tested after
  modeled replies.
- Model one follow-up scenario, but do not set real follow-up due dates.
- Preserve the warm-intro/direct-route distinction only as a synthetic route
  assumption.
- Record the public reason each candidate qualifies before generating modeled
  replies.
- Treat modeled non-replies as source-quality rehearsal only, not product
  validation.

## Outreach Execution Plan

Model Batch A first so the first five synthetic records cover all target
profiles before any single segment gets overrepresented. Model Batch B only
after Batch A has a modeled profile, reply simulation, interview record,
scorecard rehearsal, and synthesis checkpoint.

| Send batch | Candidate/team | Target slot | Draft section | Send channel | Send date | Follow-up due | Reply triage |
|------------|----------------|-------------|---------------|--------------|-----------|---------------|--------------|
| A | Markus Haverinen, Frends | 1 | Markus Haverinen, Frends | Simulated direct professional route - no real send | 2026-05-04 modeled | N/A - modeled | Modeled positive reply |
| A | Erik Munson, Day AI | 2 | Erik Munson, Day AI | Simulated direct professional route - no real send | 2026-05-04 modeled | N/A - modeled | Modeled positive reply |
| A | Lucrezia Keane, GWI | 3 | Lucrezia Keane, GWI | Simulated direct professional route - no real send | 2026-05-04 modeled | N/A - modeled | Modeled delegated reply |
| A | Jesse Zhang, Decagon | 4 | Jesse Zhang, Decagon | Simulated direct founder/operator route - no real send | 2026-05-04 modeled | N/A - modeled | Modeled brief reply |
| A | Talha Tariq, Vercel | 5 | Talha Tariq, Vercel | Simulated direct security/platform route - no real send | 2026-05-04 modeled | N/A - modeled | Modeled delegated reply |
| B | Darren Hockley, Dotdigital | 1 | Darren Hockley, Dotdigital | TBD - modeled only | TBD - modeled | N/A - modeled | Not modeled |
| B | James Luo, BGL | 2 | James Luo, BGL | TBD - modeled only | TBD - modeled | N/A - modeled | Not modeled |
| B | Nicole Looker, Rebuy Engine | 3 | Nicole Looker, Rebuy Engine | TBD - modeled only | TBD - modeled | N/A - modeled | Not modeled |
| B | Marty Kausas, Pylon | 4 | Marty Kausas, Pylon | TBD - modeled only | TBD - modeled | N/A - modeled | Not modeled |
| B | Haider Pasha, Palo Alto Networks | 5 | Haider Pasha, Palo Alto Networks | TBD - modeled only | TBD - modeled | N/A - modeled | Not modeled |

### Batch A Synthetic Readiness Notes

Use this before generating synthetic replies or interview records. No real send
channel is expected.

| Candidate/team | Modeled route stance | Anchor to preserve | First modeled reply goal |
|----------------|-----------------------------|--------------------|------------------|
| Markus Haverinen, Frends | Warm support/CS intro; otherwise approved direct professional route | Fin involvement across support conversations and human control | One concrete escalation or context-quality case |
| Erik Munson, Day AI | Warm data/platform intro; otherwise approved direct professional route | Live CRM context, permissions, and human/AI writes | One production read/write context tradeoff |
| Lucrezia Keane, GWI | Warm CS/revenue intro; otherwise approved direct professional route | Scaled CS, GRR lift, and account-state intelligence | One case where customer-state quality changed a CS action |
| Jesse Zhang, Decagon | Founder/operator intro; otherwise approved direct professional route | Customer business logic inside production support agents | One workflow-specific context workaround |
| Talha Tariq, Vercel | Security/platform intro; otherwise approved direct professional route | AI security, credentials, and developer workflow controls | One approval blocker for agent credential/API access |

### Batch A Modeled Route Decisions

Decision date: 2026-05-03. These are synthetic route assumptions for rehearsal,
not send channels. Public/profile pages are qualification context only.

| Candidate/team | Chosen route for 2026-05-04 | Public source checked | Avoid |
|----------------|-----------------------------|-----------------------|-------|
| Markus Haverinen, Frends | Approved direct professional route; warm support/CS intro only if confirmed before noon | [Fin customer story](https://fin.ai/customers/frends), public org/profile result | Public support channel |
| Erik Munson, Day AI | Approved direct professional route; warm data/platform intro only if confirmed before noon | [Materialize case study](https://materialize.com/customer-stories/day-ai/), public professional profile result | Generic Day AI company form |
| Lucrezia Keane, GWI | Approved direct professional route; warm CS/revenue intro only if confirmed before noon | [The Org profile](https://theorg.com/org/globalwebindex/org-chart/lucrezia-keane), public GWI profile result | Generic customer support route |
| Jesse Zhang, Decagon | Approved direct founder/operator route; warm founder intro only if confirmed before noon | [OpenAI customer story](https://openai.com/index/decagon/), Decagon public profile result | Sales or demo request route |
| Talha Tariq, Vercel | Approved direct security/platform route; warm security intro only if confirmed before noon | [Vercel announcement](https://vercel.com/blog/talha-tariq-joins-vercel-as-cto-security), [ITPro 1Password coverage](https://www.itpro.com/security/1password-unified-access-agent-identity-security) | Vercel support/security disclosure route |

### Batch A Send-Day Ledger

Use this for the modeled 2026-05-04 send day. Do not copy modeled values into
real PMF evidence or funnel counts.

Pre-send access check on 2026-05-03: no warm intro thread was confirmed in
accessible sources. Public/profile pages remain qualification evidence only; no
approved outbound account/session was available in this workspace. The rows
below are simulated route outcomes, not real sends.

| Candidate/team | Pre-noon route check | Final send channel | Sent timestamp | Tracker rows updated | Next action |
|----------------|----------------------|--------------------|----------------|----------------------|-------------|
| Markus Haverinen, Frends | Modeled no warm intro confirmed | Simulated direct professional route - no real send | 2026-05-04 09:10 modeled | Queue/plan/ledger marked simulated only | Use the modeled support escalation case to sharpen slot 1 probes |
| Erik Munson, Day AI | Modeled no warm intro confirmed | Simulated direct professional route - no real send | 2026-05-04 09:18 modeled | Queue/plan/ledger marked simulated only | Use the modeled read/write context tradeoff to sharpen slot 2 probes |
| Lucrezia Keane, GWI | Modeled no warm intro confirmed | Simulated direct professional route - no real send | 2026-05-04 09:26 modeled | Queue/plan/ledger marked simulated only | Use the modeled CS delegation path to sharpen slot 3 probes |
| Jesse Zhang, Decagon | Modeled no warm intro confirmed | Simulated direct founder/operator route - no real send | 2026-05-04 09:34 modeled | Queue/plan/ledger marked simulated only | Use the modeled custom-workflow boundary to sharpen slot 4 probes |
| Talha Tariq, Vercel | Modeled no warm intro confirmed | Simulated direct security/platform route - no real send | 2026-05-04 09:42 modeled | Queue/plan/ledger marked simulated only | Use the modeled approval blocker to sharpen slot 5 probes |

### Batch A Synthetic Operating Checklist

Current disposition: real outreach will not occur, so Batch A remains
`Synthetic / Modeled only`. Use this checklist to generate modeled profiles,
reply scenarios, interview records, scorecard rehearsal, and synthesis. Do not
convert any row below into PMF, pricing, funnel, or scope-gate evidence.

| Candidate/team | Candidate-specific modeled route | Required modeled artifact before synthesis | First probe from modeled stress test | Tracker rows to update after modeled work |
|----------------|--------------------------|---------------------------------|--------------------------------------|------------------------------------------|
| Markus Haverinen, Frends | Warm support/CS intro; otherwise direct professional route simulation | Modeled profile, 5 reply scenarios, interview record, and scorecard row | When did an almost-right answer create extra support work, and what data would have prevented it? | Modeled reply, scheduling intake, interview record, scorecard, segment read |
| Erik Munson, Day AI | Warm data/platform intro; otherwise direct professional route simulation | Modeled profile, 5 reply scenarios, interview record, and scorecard row | What is the first action an agent cannot safely take unless the source of truth is fresh? | Modeled reply, scheduling intake, interview record, scorecard, segment read |
| Lucrezia Keane, GWI | Warm CS/revenue intro; otherwise direct professional route simulation | Modeled profile, 5 reply scenarios, interview record, and scorecard row | Which recommendation was trusted, ignored, or overridden because the account state looked wrong? | Modeled reply, scheduling intake, interview record, scorecard, segment read |
| Jesse Zhang, Decagon | Founder/operator intro; otherwise direct founder/operator route simulation | Modeled profile, 5 reply scenarios, interview record, and scorecard row | Which customer exception broke the generic workflow, and who owned the workaround? | Modeled reply, scheduling intake, interview record, scorecard, segment read |
| Talha Tariq, Vercel | Security/platform intro; otherwise direct security/platform route simulation | Modeled profile, 5 reply scenarios, interview record, and scorecard row | What exact control would move this from rejected to a limited pilot? | Modeled reply, scheduling intake, interview record, scorecard, segment read |

After modeled work, update only modeled sections. Leave `Batch Funnel Metrics`
frozen at 0 and do not fill real `Scorecard`, `Segment Evidence Matrix`, or
real `Scope Decision Log` as evidence.

### Batch A Synthetic Respondent Profiles

Use these profiles only to keep the modeled interviews internally consistent.
They are `Synthetic / Modeled only` planning artifacts and do not identify real
participants.

| Candidate/team | Synthetic respondent profile | Modeled authority boundary | Modeled workflow pressure | Modeled segment contribution | Mode | Evidence count |
|----------------|------------------------------|----------------------------|---------------------------|------------------------------|------|----------------|
| Markus Haverinen, Frends | Support operations owner responsible for AI-assisted support quality, escalation behavior, and handoff loops | Can describe operational support risk and QA burden; cannot validate product demand | Almost-right answers create repeat handling when entitlement or escalation context is stale | Support/CS engineering contributes concrete workflow pain but weak modeled buying pressure | Synthetic / Modeled only | 0 |
| Erik Munson, Day AI | Founding/platform engineer responsible for live CRM context and agent read/write boundaries | Can describe architecture, source priority, freshness, and permissions; cannot validate budget | Agent writes are unsafe when live CRM state conflicts with recent human edits or upstream truth | Data/platform engineering contributes the strongest modeled freshness and actionability signal | Synthetic / Modeled only | 0 |
| Lucrezia Keane, GWI | Delegated CS operations owner working from scaled-account intelligence and CSM trust requirements | Can describe CS actionability and signal provenance; executive sponsor interest remains modeled only | Next-best actions stall when CSMs cannot see why product, revenue, meeting, or support signals changed the account read | Ops/revops contributes provenance risk but needs a clearer workflow owner | Synthetic / Modeled only | 0 |
| Jesse Zhang, Decagon | AI-native product founder/operator responsible for customer-specific support workflow behavior | Can describe product implementation burden; may treat context contracts as expected services work | Customer-specific policy and state exceptions force custom workflow branches | AI-native product contributes glue-burden pressure but weakens if the pain is normal implementation work | Synthetic / Modeled only | 0 |
| Talha Tariq, Vercel | Delegated security/platform reviewer responsible for approval criteria around agent API or credential access | Can describe minimum controls for a pilot; cannot validate user willingness to pay | Approval blocks on credential scope, auditability, revocation, and runtime autonomy before value is discussed | Security/governance contributes high pressure but only if a narrow pilot control exists | Synthetic / Modeled only | 0 |

### Batch A Follow-Up Drafts

Use these only as modeled follow-up language for no-reply scenarios. Do not send
them or assign real due dates.

#### Markus Haverinen, Frends

```text
Quick follow-up on this. The most useful input would be one example of where the
"plug-and-play" support AI setup needed a human escalation rule, fresher context,
or a quality loop after rollout.

If there is a case like that at Frends, I would value the pointer.
```

#### Erik Munson, Day AI

```text
Quick follow-up on this. The specific angle I'm trying to understand is where
"live" data became the difference between a fast query and an agent or user
taking a confident action.

If a tradeoff like that came up at Day AI, I would value the pointer.
```

#### Lucrezia Keane, GWI

```text
Quick follow-up on this. The example I'm looking for is a CS action where
product, revenue, support, or meeting context changed the account read.

If there is a case where the signal was trusted, ignored, or overridden, I would
value the pointer.
```

#### Jesse Zhang, Decagon

```text
Quick follow-up on this. The case I'm trying to understand is where
customer-specific business logic, stale state, or incomplete permissions forced
a custom workaround in a production support workflow.

If one example comes to mind, I would value the pointer.
```

#### Talha Tariq, Vercel

```text
Quick follow-up on this. The approval blocker I'm trying to understand is the
first thing that turns agent access from "useful" into too much credential,
privilege, or audit risk.

If one control or failure mode decides that line, I would value the pointer.
```

### Pre-Send Checklist

Complete this checklist before generating a modeled reply or interview record.

- Confirm the scenario is `Synthetic / Modeled only`.
- Keep the modeled first note to one ask: a short research conversation or a
  referral to the operator who owns the workflow.
- Remove any product name or feature claim that makes the note read like a
  pitch.
- Confirm the note names a concrete workflow risk: stale context, split state,
  unsafe access, brittle glue, escalation boundaries, or governance review.
- Do not set a real follow-up due date.
- Update only modeled rows; do not update real funnel metrics.

### Reply Triage Rules

- Positive modeled reply: create modeled scheduling intake and keep the first
  question anchored on a concrete failure or near-miss.
- Delegated reply: ask for the specific operator who owns the workflow, then
  model that operator only as a synthetic participant.
- Decline: mark the modeled outcome as declined and record the modeled reason.
- No reply: keep it as source-quality rehearsal only.
- Abstract interest without a workflow: do not count it as modeled scheduling
  intake until the scenario includes a concrete operational agent workflow.

### Batch A Reply Ledger

Use this as a modeled reply ledger only. Batch A was not sent and will not be
sent; keep non-replies and abstract interest out of PMF signal counts.

| Candidate/team | First reply date | Triage | Scheduling intake complete | Follow-up status | Mode | Evidence count |
|----------------|------------------|--------|----------------------------|------------------|------|----------------|
| Markus Haverinen, Frends | N/A - modeled | Simulated positive reply | Modeled only | N/A - modeled | Synthetic / Modeled only | 0 |
| Erik Munson, Day AI | N/A - modeled | Simulated positive reply | Modeled only | N/A - modeled | Synthetic / Modeled only | 0 |
| Lucrezia Keane, GWI | N/A - modeled | Simulated delegated reply | Modeled only | N/A - modeled | Synthetic / Modeled only | 0 |
| Jesse Zhang, Decagon | N/A - modeled | Simulated brief reply | Modeled only | N/A - modeled | Synthetic / Modeled only | 0 |
| Talha Tariq, Vercel | N/A - modeled | Simulated delegated reply | Modeled only | N/A - modeled | Synthetic / Modeled only | 0 |

### Batch A Modeled First-Reply Scenarios

These are synthetic planning scenarios. They can improve the interview script
and source-quality assumptions, but they cannot satisfy PMF gates.

| Candidate/team | Modeled first reply | Workflow detail to probe in a modeled interview | Script adjustment | Mode | Evidence count |
|----------------|---------------------|------------------------------------------|-------------------|------|----------------|
| Markus Haverinen, Frends | Positive but time-limited; willing to describe one escalation case if the conversation stays operational | A support AI answer was close but needed fresher entitlement or escalation context before a human took over | Ask for the last case where "almost right" increased handling time | Synthetic / Modeled only | 0 |
| Erik Munson, Day AI | Positive technical exchange; interested in reader/writer consistency and source priority | Live CRM context had to reconcile upstream truth, user edits, agent writes, and permissions before action | Ask what "fresh enough" means when an agent can write state | Synthetic / Modeled only | 0 |
| Lucrezia Keane, GWI | Delegates to a CS operations owner who owns scaled-account signals and recommendation trust | Account intelligence was useful only when CSMs could see which product, revenue, meeting, or support signal drove the recommendation | Ask what signal provenance a CSM needs before trusting a next action | Synthetic / Modeled only | 0 |
| Jesse Zhang, Decagon | Brief reply; notes that customer-specific business logic drives many edge cases and asks to keep it concrete | Fresh state matters less as a generic feature and more as a per-customer workflow contract | Ask for one custom workaround forced by stale state, incomplete permissions, or exception handling | Synthetic / Modeled only | 0 |
| Talha Tariq, Vercel | Delegates to a security/platform reviewer for implementation detail and approval criteria | Approval blocks first on scoped credentials, audit trail, and revocation before runtime autonomy is discussed | Ask which control turns a hard no into a limited pilot | Synthetic / Modeled only | 0 |

### Batch A Modeled Scheduling Intake

These rows simulate what scheduling intake would capture before a modeled
interview record can count. Every row remains `Synthetic / Modeled only`; do
not copy these values into the real sample plan.

| Candidate/team | Participant role | Workflow anchor | Systems touched | Risk to probe | Segment slot | Research framing | Modeled intake status | Mode | Evidence count |
|----------------|------------------|-----------------|-----------------|---------------|--------------|-------------------|-----------------------|------|----------------|
| Markus Haverinen, Frends | Support operations owner | AI-assisted support escalation and handoff | Support platform, customer account context, escalation rules | Almost-right answer, stale entitlement, unclear handoff boundary | 1 | Research only; no product pitch | Modeled complete | Synthetic / Modeled only | 0 |
| Erik Munson, Day AI | Founding engineer / platform owner | Agent reads and writes live CRM context | CRM store, upstream sources, permissions layer, agent write path | Read/write consistency, freshness, canonical entity conflicts | 2 | Research only; no product pitch | Modeled complete | Synthetic / Modeled only | 0 |
| Lucrezia Keane, GWI | Delegated CS operations owner | Scaled CS account-intelligence workflow | CRM, product usage, revenue signals, meetings, support history | Missing provenance, stale account state, overridden recommendation | 3 | Research only; no product pitch | Modeled delegated | Synthetic / Modeled only | 0 |
| Jesse Zhang, Decagon | AI-native product founder/operator | Production support agent with customer-specific workflow logic | Customer business systems, policy/config layer, support escalation path | Custom workaround, stale state, incomplete permissions | 4 | Research only; no product pitch | Modeled partial | Synthetic / Modeled only | 0 |
| Talha Tariq, Vercel | Delegated security/platform reviewer | Approval path for agent API or credential access | Secrets manager, API gateway, audit logs, revocation controls | Credential scope, auditability, runtime autonomy, revocation | 5 | Research only; no product pitch | Modeled delegated | Synthetic / Modeled only | 0 |

### Batch A Modeled Interview Stress Test

Use this to rehearse whether the interview script can separate concrete modeled
workflow pain from generic AI interest. These are hypotheses to invalidate, not
evidence.

| Segment slot | Modeled strongest signal | Modeled weak signal | Kill question for a modeled interview | Modeled planning implication |
|--------------|--------------------------|---------------------|-------------------------------|----------------------------------------|
| 1 | Human handoff quality depends on fresher account and entitlement context | Support team says the existing AI vendor already owns the whole context path | When did an almost-right answer create extra support work, and what data would have prevented it? | Prioritize support escalation context only if the model quantifies repeat handling |
| 2 | Agent write paths make freshness and permissions more painful than read-only analytics | Team treats the problem as ordinary ETL latency with no agent-specific owner | What is the first action an agent cannot safely take unless the source of truth is fresh? | Narrow modeled v1.1 around read/write operational context and provenance |
| 3 | CS teams need signal provenance before acting on AI account recommendations | The workflow is only dashboard summarization with no operational consequence | Which recommendation was trusted, ignored, or overridden because the account state looked wrong? | Stress-test CS actionability instead of broad RevOps automation |
| 4 | Customer-specific business logic forces custom context workarounds | Founder frames it as implementation detail that customers expect the platform to absorb | Which customer exception broke the generic workflow, and who owned the workaround? | Test whether product teams would value typed workflow contracts or just services |
| 5 | Security approval blocks on scoped credentials, audit, and revocation before autonomy | Security concern stays abstract with no live workflow request or approval path | What exact control would move this from rejected to a limited pilot? | Keep governance as a wedge only if the model defines a lightweight pilot path |

### Scheduling Intake

Capture these fields before a call is counted as scheduled.

| Field | Required value before scheduling |
|-------|----------------------------------|
| Participant role | The person owns, operates, approves, or debugs the workflow |
| Workflow anchor | A specific agent or AI-assisted workflow is named |
| Systems touched | At least one live operational system, support platform, CRM, data warehouse, or API boundary is named |
| Risk to probe | Stale answer, split source, unsafe access, schema drift, brittle glue, or unclear escalation |
| Segment slot | One of slots 1-5; keep no more than 2 scheduled from one slot before all slots have a credible candidate |
| Research framing | Participant understands this is not a sales call |

## Batch Funnel Metrics

Real outreach is retired for this project. Keep this table frozen so modeled
activity is never mistaken for real funnel evidence.

| Metric | Target before batch review | Current | Interpretation |
|--------|----------------------------|---------|----------------|
| Named candidates sourced | 15 | 15 | Initial sourcing target met; next constraint is outreach execution and reply quality |
| Qualified candidates | 10 | 15 | All 15 have a public signal tied to agent data access, support automation, data contracts, operational AI, or security review |
| Research notes sent | N/A - real outreach retired | 0 | Frozen; use modeled reply scenarios instead |
| Replies received | N/A - real outreach retired | 0 | Frozen; use modeled reply scenarios instead |
| Interviews scheduled | N/A - real outreach retired | 0 | Frozen; use modeled scheduling intake instead |
| Interviews completed | N/A - real outreach retired | 0 | Frozen; use modeled interview records instead |

### Synthetic Operating Metrics

Use this table as the active operating surface. It tracks modeled work only and
does not change evidence count.

| Modeled metric | Target before modeled batch review | Current | Interpretation |
|----------------|------------------------------------|---------|----------------|
| Batch A modeled candidates | 5 | 5 | Batch A covers all 5 target profiles |
| Batch A synthetic respondent profiles | 5 rows | 5 rows | Profiles are planning constraints only; evidence count remains 0 |
| Batch A modeled reply scenarios | 5 candidate sets | 5 candidate sets | Reply triage can be rehearsed without real replies |
| Batch A modeled scheduling intake | 5 rows | 5 rows | Intake fields are ready for synthetic interview records |
| Batch A modeled interview records | 5 | 5 | Enough modeled records exist for a synthetic Batch A read |
| Batch A modeled synthesis checkpoint | 1 | 1 | Use for planning only; evidence count remains 0 |
| Batch A modeled product-risk implication pass | 1 | 1 | Synthetic / Modeled only; product-risk hypotheses are planning constraints only; evidence count remains 0 |
| Batch A modeled action-safety deepening pass | 1 | 1 | Synthetic / Modeled only; blocked data/platform action-safety scenario is a hypothesis only; evidence count remains 0 |
| Batch A modeled minimum security-control scenario | 1 | 1 | Synthetic / Modeled only; limited CRM account-state write control is a hypothesis only; evidence count remains 0 |
| Batch B modeled candidates | 5 | 0 | Synthetic / Modeled only; do not model Batch B now; the product-risk, action-safety, and security-control passes create no specific modeled coverage gap |

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

## Modeled Interview Prep Checklist

Before each modeled interview record:

- Confirm the record is labeled `Synthetic / Modeled only`.
- Keep the first section focused on one modeled concrete failure or near-miss.
- Do not mention AgentFlow, MCP, LangChain, or real-time data until the optional concept test.
- Capture one synthetic quote about trust, workflow risk, maintenance burden, or governance.
- Fill the modeled scorecard immediately after generating the record.

## Modeled Interview Quality Bar

Count a modeled interview toward the synthetic 5-record batch only if it
produces enough scenario detail to stress-test the segment. This is not evidence.

| Requirement | Counts as modeled-valid | Does not count |
|-------------|-----------------|----------------|
| Concrete workflow | A named agent or AI workflow with operational data dependency | Generic AI interest or document retrieval only |
| Current workaround | Specific data path, glue code, internal tool, manual process, or vendor | "We would probably connect an API" |
| Failure or near-miss | Wrong, stale, incomplete, unsafe, blocked, or distrusted answer | Abstract concern with no incident or workflow |
| Owner | Role or team that owns the workaround or approval path | No clear owner after probing |
| Next-step signal | Pilot condition, rejection reason, budget path, or strong "not now" | Polite interest with no concrete consequence |

If a modeled record misses two or more requirements, keep it as a weak scenario
and model a stronger candidate before synthesizing the batch.

### Batch A Modeled Interview Records

These rows rehearse how the interview evidence would be captured if the modeled
Batch A conversations happened. They are synthetic records only; keep the real
per-interview log empty.

| Candidate/team | Modeled workflow discussed | Modeled failure or near-miss | Modeled current workaround | Modeled owner | Modeled next-step signal | Quality-bar rehearsal | Mode | Evidence count |
|----------------|----------------------------|------------------------------|----------------------------|---------------|--------------------------|-----------------------|------|----------------|
| Markus Haverinen, Frends | AI-assisted support escalation after automated answer confidence drops | Customer-specific entitlement context was stale enough that the AI answer needed human correction before the customer saw it | Human support lead checks account state and escalation rules before closing the loop | Support operations | Would compare whether fresher account context reduces repeat handling | Passes as a support workflow hypothesis, not evidence | Synthetic / Modeled only | 0 |
| Erik Munson, Day AI | Agent reads and writes live CRM context from multiple upstream systems | Agent-visible CRM state lagged behind a recent human edit, making a write action unsafe | Platform layer reconciles source priority, permissions, and write ownership before agent action | Platform engineering | Would test time-to-confident-action as the value metric | Passes as a data/platform hypothesis, not evidence | Synthetic / Modeled only | 0 |
| Lucrezia Keane, GWI | Scaled CS account intelligence produces next-best actions | A recommendation lacked enough signal provenance for a CSM to trust it on renewal risk | CS operations reviews product, revenue, meeting, and support signals before actioning | CS operations | Delegated operator would validate which signals change action | Partial because the modeled reply is delegated | Synthetic / Modeled only | 0 |
| Jesse Zhang, Decagon | Production support agent implements customer-specific business logic | A customer exception required a custom workflow branch because state and policy were not represented generically | Product/solutions team encodes custom policy and escalation behavior | AI product/operator | Would clarify whether typed contracts reduce custom implementation burden | Partial because buying signal is ambiguous | Synthetic / Modeled only | 0 |
| Talha Tariq, Vercel | Security review for agent API and credential access | Proposed agent access lacked enough credential scoping, audit detail, and revocation path for approval | Security/platform reviewer narrows permissions and requires auditability before pilot | Security/platform | Would define the minimum control set for a limited pilot | Partial because governance may block before a lightweight pilot | Synthetic / Modeled only | 0 |

## Modeled Per-Interview Record

Copy this block after each modeled interview.

```text
Modeled interview:
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
Budget owner:
Replaceable cost:
Natural value metric reaction:
Pilot shape:
Pricing risk:
Exact quote worth keeping:
Follow-up needed:
```

Pricing fields are synthetic planning fields only. Do not turn them into price
points, tiers, pricing-page copy, or pricing evidence.

## Real Scorecard

Real scoring is retired because no real interviews will occur. Keep this table
empty and use `Batch A Modeled Scorecard Rehearsal` for synthetic scoring.

| Slot | Pain severity | Freshness criticality | Glue burden | Ownership clarity | Pilot readiness | Budget/WTP signal | Governance pressure | Total |
|------|---------------|-----------------------|-------------|-------------------|-----------------|-------------------|---------------------|-------|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 5 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

### Batch A Modeled Scorecard Rehearsal

Use these scores as synthetic planning inputs only. They are not PMF evidence
and do not populate the real scorecard.

| Slot | Pain severity | Freshness criticality | Glue burden | Ownership clarity | Pilot readiness | Budget/WTP signal | Governance pressure | Modeled total | Rehearsal read | Mode | Evidence count |
|------|---------------|-----------------------|-------------|-------------------|-----------------|-------------------|---------------------|---------------|----------------|------|----------------|
| 1 | 2 | 2 | 1 | 2 | 1 | 0 | 1 | 9 | Support pain is concrete, but modeled value still depends on repeat handling reduction | Synthetic / Modeled only | 0 |
| 2 | 2 | 3 | 2 | 3 | 2 | 1 | 2 | 15 | Data/platform is strongest in the model because read/write action makes freshness operational | Synthetic / Modeled only | 0 |
| 3 | 1 | 2 | 1 | 2 | 1 | 0 | 1 | 8 | CS signal is plausible, but delegated ownership must become concrete before counting | Synthetic / Modeled only | 0 |
| 4 | 2 | 1 | 3 | 2 | 1 | 1 | 1 | 11 | AI-native product pain is strong in the model but could collapse into bespoke services work | Synthetic / Modeled only | 0 |
| 5 | 2 | 1 | 1 | 2 | 1 | 0 | 3 | 10 | Security pressure is high, but pilot readiness is the key modeled risk | Synthetic / Modeled only | 0 |

## Segment Evidence Matrix

Real segment evidence is retired because no real interviews will occur. Keep
this table frozen and use the modeled segment read below for planning.

| Segment | Concrete failure count | Strong buying signals | Strong rejection signals | Segment read |
|---------|------------------------|-----------------------|--------------------------|--------------|
| Support/CS engineering | 0 | TBD | TBD | TBD |
| Data/platform engineering | 0 | TBD | TBD | TBD |
| Ops/revops | 0 | TBD | TBD | TBD |
| AI-native product | 0 | TBD | TBD | TBD |
| Security/governance | 0 | TBD | TBD | TBD |

### Batch A Modeled Segment Read

This is the active planning read for synthetic mode. It remains `Synthetic /
Modeled only` and evidence count remains `0`.

| Segment | Batch A candidate contribution | Modeled read | Synthetic planning implication | Mode | Evidence count |
|---------|------------------------------|--------------|---------------------------|------|----------------|
| Support/CS engineering | Markus contributes the almost-right answer and human handoff scenario | Concrete support-risk language is easy to elicit, but modeled buying pressure is weaker than workflow pain | Quantify modeled repeat handling, escalation cost, and answer-quality ownership before prioritizing | Synthetic / Modeled only | 0 |
| Data/platform engineering | Erik contributes the live CRM read/write and source-priority conflict | Strongest modeled wedge because stale state blocks safe agent action, not just reporting | Stress-test read/write context, source priority, and permission provenance first | Synthetic / Modeled only | 0 |
| Ops/revops | Lucrezia contributes delegated CS signal-provenance and next-best-action trust | Account intelligence needs provenance before action, but the modeled path depends on delegated access | Model the operator who owns the CS or RevOps workflow, not only the executive sponsor | Synthetic / Modeled only | 0 |
| AI-native product | Jesse contributes the customer-specific workflow-contract and custom workaround burden | Custom workflow logic is painful, but may be expected implementation work inside the product category | Separate platformizable context contracts from normal services delivery in the model | Synthetic / Modeled only | 0 |
| Security/governance | Talha contributes the delegated approval-control and scoped-credential blocker | Governance is intense but can become a hard no unless a narrow pilot control exists | Define the modeled minimum control set before discussing autonomy | Synthetic / Modeled only | 0 |

### Batch A Modeled Synthesis Checkpoint

This checkpoint summarizes the rehearsal only. It is not a scope decision and
does not unlock v1.1 product work as validated PMF evidence.

| Modeled question | Rehearsal read | Next synthetic action | Mode | Evidence count |
|------------------|----------------|------------------------|------|----------------|
| Which segment has the clearest operational consequence? | Data/platform engineering, because read/write agent context turns freshness into a safety and actionability problem | Model one blocked agent action and its source-of-truth conflict | Synthetic / Modeled only | 0 |
| Which segment may be easiest to access first? | Support/CS, because escalation and answer-quality examples are easy to explain without product framing | Model repeat handling, escalation cost, and QA ownership pressure | Synthetic / Modeled only | 0 |
| Which segment is most likely to stall? | Security/governance, because approval can become abstract unless tied to a specific live workflow request | Model the minimum control set that permits a limited pilot | Synthetic / Modeled only | 0 |
| Which question should lead the next modeled record? | Ask for the last concrete moment when an AI workflow could not safely act because live business context was stale, missing, split, or unsafe | Capture workflow, systems touched, owner, workaround, and pilot condition before any concept test | Synthetic / Modeled only | 0 |
| Does Batch B need modeling now? | No; Batch A covers all five modeled target profiles and leaves no segment-coverage gap | Keep Batch B at 0 modeled candidates unless a specific modeled gap appears after the product-risk implication pass | Synthetic / Modeled only | 0 |

### Batch A Modeled Product-Risk Implications

This pass is `Synthetic / Modeled only`. The implications below are hypotheses
for planning discipline only. They are not PMF, pricing, segment, roadmap,
release-readiness, or scope evidence, and evidence count remains `0`.

| Product-risk implication | Expanded Batch A synthetic read | Hypothesis-only planning implication | Batch B decision impact | Mode | Evidence count |
|--------------------------|---------------------------------|--------------------------------------|-------------------------|------|----------------|
| Action-safety risk may be the clearest wedge | Data/platform shows the strongest modeled pressure because stale or split state blocks safe read/write agent action | Hypothesis only: pressure-test blocked actions, source priority, permissions, and provenance before any product or roadmap decision | No Batch B gap; Batch A already includes data/platform and governance anchors | Synthetic / Modeled only | 0 |
| Support value may stay operational rather than strategic | Support/CS produces concrete almost-right-answer risk, but modeled buying pressure is weaker than workflow pain | Hypothesis only: quantify repeat handling, escalation cost, and answer-quality ownership without treating support pain as PMF or pricing evidence | No Batch B gap; the next modeled need is depth on support economics, not another segment | Synthetic / Modeled only | 0 |
| Provenance and owner clarity may matter more than freshness alone | Ops/revops depends on whether a delegated operator can explain which signal changed the account read | Hypothesis only: require a modeled workflow owner, signal path, and decision point before using this as a segment hypothesis | No Batch B gap; Batch A already exposes the delegated-owner risk | Synthetic / Modeled only | 0 |
| AI-native product pain may collapse into bespoke services work | Customer-specific workflow contracts and exceptions look painful, but may be expected implementation work | Hypothesis only: separate platformizable context contracts from normal customer-specific glue before any scope assumption | No Batch B gap; the unresolved question is platformizability inside the modeled slot | Synthetic / Modeled only | 0 |
| Governance may block value testing before release readiness is knowable | Security/governance pressure is high, but approval depends on scoped credentials, auditability, and revocation | Hypothesis only: model the minimum control set for a limited pilot; do not treat governance pressure as release-readiness evidence | No Batch B gap; the current gap is a control-set question, not missing segment coverage | Synthetic / Modeled only | 0 |
| Batch B is not justified as a coverage pass now | Expanded Batch A has modeled profiles, replies, intake, interview records, scorecard rehearsal, segment read, and synthesis for all five target profiles | Hypothesis only: deepen one blocked action or one minimum-control scenario before adding more modeled candidates | Leave Batch B at 0 until a specific uncovered workflow or segment gap is named | Synthetic / Modeled only | 0 |

### Batch A Modeled Action-Safety Deepening Pass

This pass is `Synthetic / Modeled only`. It deepens exactly one blocked
data/platform action-safety scenario as a hypothesis only. It is not PMF,
pricing, segment, roadmap, release-readiness, scope, or evidence-gate evidence;
real funnel metrics and evidence count remain `0`.

| Deepening pass | Modeled blocked action | Modeled source-of-truth conflict | Modeled safety failure | Modeled current control/workaround | Hypothesis-only planning implication | Batch B decision impact | Mode | Evidence count |
|----------------|------------------------|----------------------------------|------------------------|------------------------------------|--------------------------------------|-------------------------|------|----------------|
| Data/platform action-safety: CRM account-state write blocked | Agent attempts to update account health and renewal-risk state after a support escalation and billing-plan change | CRM has a recent human edit, billing entitlement state lags, and the support note records an exception without a canonical priority rule | The modeled agent cannot safely write because it cannot prove which system owns the current account state or why one value should override another | Platform owner requires read-only mode until source priority, permission provenance, and human review path are explicit | Hypothesis only: the wedge may be an action-safety contract that names source priority, freshness, permission provenance, and review fallback before write access | No Batch B gap; this deepens the existing data/platform slot and does not expose an uncovered segment or workflow | Synthetic / Modeled only | 0 |

### Batch A Modeled Minimum Security-Control Scenario

This pass is `Synthetic / Modeled only`. It records exactly one minimum
security-control scenario for the blocked CRM account-state write as a
hypothesis only. It is not PMF, pricing, segment, roadmap, release-readiness,
scope, or evidence-gate evidence; real funnel metrics and evidence count remain
`0`.

| Security-control scenario | Modeled trigger | Minimum modeled controls | Modeled approval boundary | Hypothesis-only planning implication | Batch B decision impact | Mode | Evidence count |
|---------------------------|-----------------|--------------------------|---------------------------|--------------------------------------|-------------------------|------|----------------|
| Limited CRM account-state write control | Agent remains blocked from updating account health and renewal-risk state after a support escalation and billing-plan change | Field-scoped service credential for account-health and renewal-risk writes, source-priority proof, permission provenance, audit log, and human review before commit | Security/platform permits only read-only rehearsal or reviewed write; no autonomous production write and no real pilot approval | Hypothesis only: a limited pilot may require field scope, source-priority proof, auditability, and review fallback before testing action safety | No Batch B gap; this deepens the existing data/platform and security/governance slots without exposing an uncovered segment or workflow | Synthetic / Modeled only | 0 |

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

## Modeled Batch Synthesis Workflow

After all 5 modeled interview records are recorded:

1. Copy the strongest synthetic quote from each modeled interview into the synthesis template.
2. Count how many modeled records included a concrete failure or near-miss.
3. Count how many modeled records scored `2` or higher for glue burden, ownership clarity,
   pilot readiness, budget/WTP signal, or governance pressure.
4. Group the records by workflow type: support/CS, data/platform, ops/revops,
   AI-native product, security/governance.
5. Compare the strongest modeled segment against the synthetic decision gates below.
6. Decide whether v1.1 scope stays intact, narrows, or pauses for more modeling.

## Modeled Scope Decision Log

Fill this only after the 5-record modeled batch is complete. Every row remains
`Synthetic / Modeled only` and evidence count remains `0`.

| Decision | Result |
|----------|--------|
| Batch date range | 2026-05-04 modeled; Synthetic / Modeled only; evidence count 0 |
| Modeled interviews completed | 5 / 5 synthetic records; Synthetic / Modeled only; evidence count 0 |
| Concrete failures or near-misses | 5 modeled near-misses; Synthetic / Modeled only; evidence count 0 |
| Strongest segment | Data/platform engineering as a modeled planning hypothesis; Synthetic / Modeled only; evidence count 0 |
| Weakest assumption | Pilot readiness and budget pressure remain unvalidated; Synthetic / Modeled only; evidence count 0 |
| Scope decision | No real scope decision; do not update roadmap, release-readiness, pricing, or PMF evidence; Synthetic / Modeled only; evidence count 0 |
| Next product action | Use modeled-only product-risk implications as hypotheses without changing evidence gates; Synthetic / Modeled only; evidence count 0 |
| Batch B decision | Product-risk implication pass creates no specific modeled gap; leave Batch B at 0; Synthetic / Modeled only; evidence count 0 |
| Evidence link | Synthetic / Modeled only; evidence count 0 |

## Synthetic Decision Gates After 5 Modeled Interviews

Use the current v1.1 direction as a modeled planning assumption only if the
synthetic batch shows:

- At least 3 modeled records include a concrete failure or near-miss.
- At least 3 modeled records score `2` or higher on glue burden, ownership clarity,
  or pilot readiness.
- At least 2 modeled records show a plausible 30-60 day pilot path.
- Existing vendor or internal-build alternatives are not clearly "good enough"
  for the target workflow.

Change the roadmap before implementation if:

- Most teams describe only document retrieval or generic NL-to-SQL needs.
- Freshness/trust is not tied to a modeled workflow consequence.
- Buyers value protocol support but do not care about typed contracts,
  provenance, or safe serving boundaries.
- Governance dominates every promising conversation before a lightweight pilot
  can be defined.

## Modeled Batch Review Outcomes

Pick exactly one synthetic planning outcome after the first valid 5-record
modeled batch.

| Outcome | When to choose it | Next action |
|---------|-------------------|-------------|
| Continue v1.1 direction as modeled plan | Synthetic gates pass and one segment is clearly strongest | Draft a narrow v1.1 PRD with `Synthetic / Modeled only` caveat |
| Narrow the modeled wedge | Modeled pain clusters around one workflow or buyer | Rewrite scope around that workflow before building |
| Run another modeled discovery batch | Synthetic signal is mixed but at least two modeled records are promising | Model 5-10 more candidates in the strongest segment |
| Pause product work | Modeled records stay abstract, low-pain, or ownerless | Do not build v1.1 features until the model produces a stronger pain |

## Synthesis Template

After 5 modeled interviews, summarize:

- strongest modeled pain:
- weakest assumption:
- best-fit ICP segment:
- strongest synthetic quote:
- most common alternative:
- most plausible pilot shape:
- v1.1 scope change required:
- confidence: Synthetic / Modeled only; evidence count 0
