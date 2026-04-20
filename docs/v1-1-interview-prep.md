# v1.1 Interview Preparation Report

**Date**: 2026-04-20  
**Type**: Synthetic research - thought exercise, NOT primary research  
**Next step**: founder conducts 5 real interviews using `docs/customer-discovery-questions.md`

## Executive Summary

The synthetic interview pass increased confidence that AgentFlow's real wedge is not "real-time" in the abstract and not protocol support by itself. The sharper value proposition is a read-first, contract-aware serving boundary for operational agent workflows: typed entities and metrics, explicit freshness/provenance, and safer access over live business systems. The next real risk to validate is whether mid-market teams feel this pain strongly enough to pilot before enterprise governance demands dominate the roadmap.

## Inputs used

- `docs/v1-1-research.md`
- `docs/competitive-analysis.md`
- `.tmp/research-customer-discovery.md`
- `.tmp/synthetic-interviews/*.md`
- `.tmp/synthetic-interviews/meta-analysis.md`

## What synthetic interviews taught us

- The strongest pain is usually **trust in answers**, not "freshness" as a standalone word.
- Mature teams already know how to move data quickly; they struggle with safe serving contracts, ownership, provenance, and change management.
- Small teams mostly describe the problem as glue-code sprawl and mixed cached/live paths, not as missing infrastructure.
- Enterprise teams reinforce the need for governance, but they are likely to be a slow and roadmap-heavy first wedge.
- Structured entities and metrics matter most when the agent can trigger or influence a real action.
- Framework support matters, but it should stay subordinate to one shared serving contract.

## Updated interview script

The founder-ready script now lives in `docs/customer-discovery-questions.md`.

The main changes versus the earlier question set:

- Start with the last concrete failure, not with abstract freshness preferences.
- Separate stale data, split-source entities, schema/change-management drift, and unsafe access.
- Ask who owns the current workaround and who gets pulled in when it breaks.
- Delay MCP/framework questions until late in the call.
- Score pain severity, glue burden, governance pressure, owner clarity, and pilot readiness after every call.

## v1.1 hypothesis: updated confidence

| Hypothesis | Before synthetic | After synthetic | Change |
|-----------|------------------|-----------------|--------|
| MCP is the highest-leverage interoperability surface | medium-high | medium | Narrower: still important, but not sufficient as headline value |
| LangChain thin adapter should stay secondary to the shared contract | medium | medium-high | Slightly stronger: useful, but clearly not the main product story |
| Freshness primitives are a top v1.1 priority | high | high | Reframed: freshness must be explicit and caller-visible, not just "fast" |
| Contracts/versioning/provenance are monetizable for the best-fit ICP | medium | medium-high | Stronger: repeated signal from mature personas |

## Working ICP after the synthetic pass

**Best-fit near-term ICP**

Mid-market to upper-mid-market teams already piloting or running operational agents where wrong answers create adoption drag, on-call cost, or trust issues. These teams usually have multiple business systems, some governance pressure, and too much custom glue, but they do not want to buy another full data platform.

**Lower-priority segments**

- Solo founders or hobby-scale builders who want speed and a cheap/free tier more than guarantees
- Pure document-RAG teams with little operational freshness need
- Enterprise buyers whose procurement and security demands will dominate roadmap scope before the wedge is proven

## Risks to validate in real interviews

- Do target teams say "freshness" naturally, or do they frame the problem as trust, glue, or governance?
- Is there a real owner and pilot path, or only broad verbal agreement?
- Does protocol choice matter in practice, or is it just implementation detail after contracts and access boundaries are solved?
- Are teams willing to pay for contract/versioning/freshness semantics, or do they only value onboarding convenience?
- How often does "do nothing and keep hacking" beat a category purchase for the startup segment?
- Can Persona-3-style teams move fast enough to be the first strong GTM wedge?

## Recommendation

Proceed with the v1.1 direction, but tighten the story:

- Lead with **safe operational truth for agents**, not generic "real-time."
- Keep **read-first MCP** as the broad interoperability bet.
- Keep **LangChain/LangGraph support** thin and downstream of the same contract surface.
- Treat **freshness, provenance, and contract/versioning** as first-class product semantics.
- Do not let enterprise-only requirements become the whole roadmap before real mid-market interviews confirm the wedge.

## Immediate next actions for the founder

1. Run 5 real interviews using `docs/customer-discovery-questions.md`.
2. Keep the sample skewed toward support, ops, and other workflows touching live business state.
3. After each call, fill the scorecard and collect one exact quote that captures the pain.
4. Revisit v1.1 scope only after comparing the 5 real interviews against the synthetic expectations in `.tmp/synthetic-interviews/meta-analysis.md`.
