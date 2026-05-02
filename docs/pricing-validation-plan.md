# AgentFlow Pricing Validation Plan

**Date:** 2026-05-02
**Status:** pre-PMF research plan, not a pricing page
**Discovery input:** [Customer Discovery Tracker](customer-discovery-tracker.md)
**Competitive baseline:** [Competitive Analysis](competitive-analysis.md)

This plan keeps pricing work tied to real customer evidence. Do not publish
price points, tiers, or sales collateral from this document alone.

## Research Goal

Validate whether AgentFlow should be packaged around agent-safe operational
serving, data freshness/trust, integration workload, governance, or a simpler
developer adoption motion.

The first pricing decision is not "what number should go on the page." The first
decision is which value metric buyers naturally accept after describing a real
workflow pain.

## Candidate Value Metrics To Test

| Metric | What it tests | Watch for |
|--------|---------------|-----------|
| Workspace or environment | Whether buyers think of AgentFlow as shared agent infrastructure | Works if platform/security owns the problem |
| Connected source | Whether integration breadth maps to perceived value | Risk: pushes the product toward connector-count pricing |
| Served entity or contract | Whether typed business objects are the value anchor | Works if contracts/versioning/provenance are memorable |
| Request or workload volume | Whether usage scales with value in production | Risk: can feel like unpredictable infra billing |
| Pilot package | Whether buyers need a low-friction evaluation path | Useful before repeatable self-serve pricing exists |

## Questions To Add During Discovery

Use these only after the interviewee has described a concrete workflow or
workaround. Do not lead with pricing.

1. What team budget would this realistically come from if the problem were solved?
2. What current tool, vendor, internal project, or team time would it replace?
3. Would the buyer expect to pay for environments, data sources, business
   entities, requests, seats, or a fixed pilot?
4. What usage pattern would make pricing feel unpredictable or risky?
5. What would a 30-60 day paid pilot need to include to feel worth approving?
6. What would make the product feel too cheap to trust for this workflow?
7. What would make it feel expensive but still worth evaluating?

## Pricing Signals To Capture

Pricing work should reuse the discovery tracker instead of creating a separate
survey too early. Add these signals to each interview note when the conversation
reaches budget, buying motion, or pilot shape.

| Signal | Tracker field | Useful evidence | Weak evidence |
|--------|---------------|-----------------|---------------|
| Budget owner | Strongest buying signal | Names a team, budget, or approval path | "Engineering would probably care" |
| Replaceable cost | Current workaround | Specific engineering time, vendor spend, or delay cost | Generic frustration |
| Natural value metric | Follow-up needed | Interviewee volunteers a pricing unit or rejects one clearly | Nods through every option |
| Pilot shape | Strongest buying signal | 30-60 day scope, success criteria, and buyer | "Maybe worth trying someday" |
| Pricing risk | Strongest rejection signal | Predictability, procurement, compliance, or usage anxiety | No concrete objection |

## Evidence Gates

Do not choose a public pricing model until the first 5-interview batch shows:

- At least 2 interviews name a plausible budget owner.
- At least 2 interviews identify a replaceable cost: internal engineering time,
  vendor spend, slower rollout velocity, or support/on-call burden.
- At least 2 interviews describe a credible paid pilot path.
- At least 3 interviews react clearly to one value metric as natural or unnatural.

If those gates are not met, keep pricing as founder-led pilot scoping rather than
self-serve tiers.

## First Pilot Offer Shape To Test

Do not test dollar amounts yet. Test whether buyers can describe a pilot that is
narrow enough to approve and valuable enough to pay for.

| Component | Default hypothesis | Reject if interviews show |
|-----------|--------------------|---------------------------|
| Scope | One workflow, two to three live operational sources, typed entities and metrics | Buyers only need generic document retrieval or analytics |
| Duration | 30-60 days | Evaluation requires a long platform migration first |
| Success criteria | Correctness, freshness visibility, lower glue maintenance, safer access | Buyers cannot name a measurable workflow outcome |
| Buyer | Platform, CS engineering, ops, or AI product owner | No one owns the pain or budget |
| Pricing posture | Founder-led paid pilot before self-serve tiers | Buyers expect a free open-source library, not a paid workflow outcome |

## Packaging Hypotheses

| Hypothesis | Evidence needed | Failure signal |
|------------|-----------------|----------------|
| Pilot package first | Buyers can define a narrow workflow and 30-60 day success criteria | Calls stay abstract or budget owner is unclear |
| Platform tier later | Multiple teams/systems need shared contracts and governance | Pain stays inside one small workflow |
| Usage pricing later | Production value scales with request or workload volume | Buyers fear unpredictable infra-style bills |
| Contract/entity metric | Buyers remember typed entities, provenance, and versioning as the value | Buyers only care about connector setup speed |

## Post-Batch Pricing Decision

After 5 interviews, fill this table before changing the roadmap or publishing
pricing copy.

| Decision | Result |
|----------|--------|
| Most natural value metric | TBD |
| Strongest budget owner | TBD |
| Replaceable cost | TBD |
| Paid pilot shape | TBD |
| Pricing model to test next | TBD |
| Pricing model to avoid | TBD |
| Confidence | Low / Medium / High |
