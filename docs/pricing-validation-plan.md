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

## Evidence Gates

Do not choose a public pricing model until the first 5-interview batch shows:

- At least 2 interviews name a plausible budget owner.
- At least 2 interviews identify a replaceable cost: internal engineering time,
  vendor spend, slower rollout velocity, or support/on-call burden.
- At least 2 interviews describe a credible paid pilot path.
- At least 3 interviews react clearly to one value metric as natural or unnatural.

If those gates are not met, keep pricing as founder-led pilot scoping rather than
self-serve tiers.

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

