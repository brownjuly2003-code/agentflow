# AgentFlow v1.1 Research

**Date**: 2026-04-20
**Purpose**: inform v1.1 feature priorities before implementation
**Scope**: research only, no code

## Executive Summary

The strongest public-market signal is not "add more framework adapters." It is "ship a trustworthy agent access surface over existing data systems," and the dominant first-party surface for that in 2026 is MCP. AgentFlow should therefore prioritize a read-first MCP surface for v1.1, keep a thin LangChain adapter as a high-value supported path, and treat LlamaIndex as a secondary retrieval bridge rather than the primary wedge. The real differentiation is not protocol choice alone; it is typed operational entities and metrics, explicit freshness signals, and a contract-first serving layer that database vendors and analytics APIs do not center today.

## 1. Agentic Frameworks Integration Patterns

### Summary judgement

- LangChain remains the most important framework-specific integration target.
- LlamaIndex is relevant, but mainly when AgentFlow acts like a reader/retriever into document-style workflows.
- MCP is the broadest cross-ecosystem surface and should be treated as an emerging standard, not a niche experiment.

### LangChain

**Observed pattern**

- LangChain expects a small set of tools with clear descriptions and explicit schemas.
- The framework supports both lightweight `@tool` definitions and richer tool classes/toolkits.
- Common data-access patterns are still:
  - SQL toolkits for structured querying
  - retriever/vector tools for semantic search
  - custom domain tools for business workflows
- LangChain now also has first-party MCP documentation, which is a strong signal that the ecosystem is normalizing around protocol-based tool distribution rather than bespoke wrappers alone.

**What that means for AgentFlow**

AgentFlow should not present itself to LangChain as a giant mirror of raw endpoints. It should expose a narrow, obvious business tool surface. The model should see tools like "get an order," "get a metric," or "check freshness," not a pile of generic transport primitives.

**Recommended LangChain surface**

- `get_entity`
- `search_entities`
- `get_metric`
- `check_freshness`
- `list_contracts`
- optional `stream_recent_events`

**Why this is preferable**

- Better tool selection quality
- Lower context/token overhead
- Lower overlap between tools
- Easier evals and prompt debugging
- Cleaner buyer story than "AI over raw SQL"

**Recommended integration approach for AgentFlow**

Keep the LangChain integration task-oriented and contract-first. Every response should carry enough metadata to help the agent know whether the answer is fresh and what contract or source it came from. If the tool surface grows, defer the long tail through MCP or similar loading patterns instead of handing the model dozens of tools up front.

**Code sketch**

```python
from agentflow_integrations.langchain import AgentFlowToolkit
from langchain.agents import initialize_agent

toolkit = AgentFlowToolkit("http://localhost:8000", api_key="af-dev-key")
agent = initialize_agent(
    toolkit.get_tools(),
    llm,
    agent="zero-shot-react-description",
)
```

**Confidence**: High

### LlamaIndex

**Observed pattern**

- LlamaIndex remains document/reader/index/query-engine centric.
- The common flow is:
  - load data with a reader
  - convert to documents
  - build an index such as `VectorStoreIndex`
  - expose it through a query engine or agent tool
- The platform also has document refresh semantics and managed syncing paths, which matter for freshness-sensitive workloads.

**What that means for AgentFlow**

LlamaIndex is a useful bridge when AgentFlow is supplying live business context into retrieval-oriented or synthesis-oriented workflows. It is less compelling as the primary serving contract for hard real-time operational reads where freshness and source-of-truth guarantees matter more than document composition.

**Recommended LlamaIndex approach**

- Maintain a thin `AgentFlowReader`
- Convert live entities/metrics into `Document`s with metadata:
  - `as_of`
  - `freshness_window`
  - `source_system`
  - `contract_version`
- Use LlamaIndex for:
  - retrieval over curated slices
  - synthesis over snapshots
  - blended document + operational context
- Do not let embeddings or cached documents silently stand in for live business truth

**Code sketch**

```python
from agentflow_integrations.llamaindex import AgentFlowReader
from llama_index.core import VectorStoreIndex

reader = AgentFlowReader("http://localhost:8000", api_key="af-dev-key")
documents = reader.load_data(
    entity_type="order",
    metric_names=["revenue", "order_count"],
    window="24h",
)

index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()
```

**Confidence**: Medium-high

### MCP

**Status**

Emerging standard.

As of 2026-04-20, that assessment is supported by:

- OpenAI documentation stating that MCP is becoming the industry standard
- Anthropic documentation continuing to frame MCP as the open protocol for model-to-system connectivity
- first-party LangChain MCP docs
- the official protocol spec, SDKs, Streamable HTTP transport, and auth guidance
- multiple data vendors now publishing official MCP surfaces

**What that means for AgentFlow**

MCP is the right interoperability surface for broad ecosystem reach, but it should not replace AgentFlow's typed SDKs and direct HTTP API. It should sit beside them.

**Best v1.1 MCP shape**

- Read-first only
- Small tool set
- Strong descriptions
- Explicit auth scopes
- Explicit freshness metadata
- Clear read/write boundaries

**Recommended initial MCP tools**

- `search_entities`
- `fetch_entity`
- `get_metric`
- `check_freshness`
- `list_contracts`
- `fetch_contract_changelog`

**Why not make MCP the only interface**

- Application code still benefits from typed SDKs
- Some runtime workloads do not want tool-call overhead
- Non-agent consumers still need a stable direct API contract
- Protocol support varies by runtime and security posture

**Confidence**: High

### Tool-use best practices to adopt in v1.1

These patterns repeat across current OpenAI, Anthropic, and LangChain guidance:

- Keep the initial callable surface small
- Prefer strict schemas over permissive best-effort inputs
- Use detailed tool descriptions and parameter descriptions
- Do not ask the model for arguments the application already knows
- Summarize old tool outputs when context grows, but fetch fresh operational truth on demand

**Implication for AgentFlow**

Tool ergonomics is part of product quality. A strong data plane with vague or overlapping tools will still perform poorly in real agent loops.

### Agent memory and freshness

The synthesis across sources is clear:

- memory is good for user/task state
- live business truth should stay in tools/data layer
- freshness boundaries must be explicit whenever data is cached, indexed, or summarized

That maps cleanly to AgentFlow's position as the operational truth boundary for agents.

## 2. Competitive Integration Landscape

### Table

| Product | LangChain? | LlamaIndex? | MCP? | Agent-specific docs? | Our differentiation |
|---------|------------|-------------|------|----------------------|---------------------|
| Tinybird | No first-party LangChain page found in public docs | No first-party LlamaIndex page found | Yes | Yes | Typed operational contracts and freshness semantics, not analytics APIs plus MCP |
| Materialize | No first-party LangChain page found | No first-party LlamaIndex page found | Yes | Yes | Simpler app-facing contract layer, less infrastructure gravity |
| Neon | No first-party LangChain page found; official docs emphasize agent frameworks like LangGraph and AutoGen instead | No first-party LlamaIndex page found | Yes | Yes | Serving layer above databases, not another agent database backend |
| Supabase | No first-party LangChain page found | No first-party LlamaIndex page found | Yes | Yes | Multi-source business serving and freshness guarantees, not only project-scoped database access |
| MotherDuck | Yes | No first-party LlamaIndex page found | Yes | Yes | Operational freshness and business-entity contracts over warehouse-style AI access |
| Vercel platform | No first-party LangChain page found | No first-party LlamaIndex page found | Yes | Yes | Vendor-neutral serving layer rather than app-platform feature |
| Rockset | Historical benchmark only | Historical benchmark only | No current standalone product surface found | No current standalone product surface | AgentFlow is available to evaluate now |

### What the market is actually doing

**1. MCP is the default first-party integration bet**

This is the clearest pattern in the market scan. Data vendors are not waiting for community wrappers. They are shipping official MCP surfaces directly in their docs.

**2. Framework-specific first-party adapters are selective**

MotherDuck has an official LangChain page. Neon focuses more on agent frameworks and application patterns than on LangChain/LlamaIndex-specific adapter matrices. Tinybird, Materialize, and Supabase appear to emphasize product-native agent docs and MCP more than framework-specific pages.

**3. The category language is getting crowded**

Materialize explicitly uses "apps and AI agents." Neon uses "AI tools" and agent backends. Tinybird has a dedicated AI agents area. MotherDuck has AI/MCP/LangChain docs. This means "built for agents" is not differentiating copy anymore.

### Product notes

#### Tinybird

- Strong self-serve story
- Strong SQL-to-API positioning
- Strong MCP support
- Weakest fit for AgentFlow differentiation if AgentFlow leads with generic API-generation or analytics language

**Implication**

Compete on typed operational truth and freshness visibility, not on "fast queries for AI."

#### Materialize

- Strongest freshness credibility in the set
- Live data layer message is already mature
- Official MCP docs reinforce agent relevance

**Implication**

Do not fight on engine depth. Fight on contract safety, lower complexity, and faster path from data to agent-ready reads.

#### Neon

- Clear "database for AI" messaging
- Strong agent-framework adjacency
- Strong agent-backend posture

**Implication**

AgentFlow should not drift into "persistent memory database for agents." Its better wedge is the business-serving boundary above raw databases.

#### Supabase

- Huge developer distribution
- Official MCP support
- Clear security framing around MCP

**Implication**

Compete where teams need more than direct database/project access and where freshness, joins, policy, or contract stability matter.

#### MotherDuck

- Strongest example of dual-track support: official MCP plus official LangChain
- Familiar SQL/analytics posture
- Good explainability fit for buyers already in DuckDB world

**Implication**

If AgentFlow ignores MCP, it falls behind the market. If it ignores contracts/freshness, it becomes another "talk to your data" tool.

#### Vercel platform

- Official MCP server and Agent Tools exist
- Vercel Postgres itself was discontinued on 2024-12-31
- The platform is moving toward agent tooling plus partner data integrations

**Implication**

Treat Vercel as a distribution/runtime signal, not as a data-engine benchmark. The important lesson is speed: platform vendors are packaging agent surfaces quickly.

#### Rockset

- Still useful as a historical reference point
- No longer useful as a standalone self-serve product benchmark

**Implication**

Do not spend v1.1 planning cycles optimizing for a head-to-head benchmark that buyers cannot run today.

### Competitive findings

#### What competitors do well

- Official MCP surfaces
- Self-serve onboarding
- "Connect to your existing data" messaging
- Clear documentation close to the core product

#### What competitors do not center

- Typed business contracts as the core abstraction
- Freshness as a caller-visible contract
- Multi-source operational serving for agents
- A narrow story around safe agent consumption of live business entities and metrics

#### Risks of copying them

- Copying generic "query your data with AI" copy lands AgentFlow in a crowded, undifferentiated pool
- Copying infrastructure-first language pulls the product into comparisons it does not need
- Copying database-vendor MCP without a stronger application contract story makes AgentFlow look replaceable

### Positioning AgentFlow v1.1

AgentFlow should position as the contract-first freshness layer for AI agents that need operational business truth, not just database access. The story should be:

- typed entities and metrics
- explicit freshness signals
- multi-source context assembly
- small, trustworthy SDK and MCP surfaces
- lower integration burden than building custom APIs around live systems

**Confidence**

- High confidence on the MCP adoption pattern
- Medium confidence on negative statements such as "no first-party LangChain page found," because those are based on public-doc review and focused search, not private roadmaps

## 3. Customer Discovery Kit

### Target ICP

Primary target:

- engineering teams of 5-50 people
- already building AI agents or agent-like automations
- need live operational answers, not only document retrieval
- feel pain from stale data, custom glue code, or schema drift in agent workflows

Best-fit examples:

- support agent answering order/account questions
- ops agent watching pipeline or fulfillment state
- internal assistant that needs business truth from multiple systems

Poor-fit examples:

- pure content/marketing agents
- pure document-RAG use cases with no operational freshness need
- teams that only need realtime UI sync

### Interview logistics

- Duration: 30 minutes
- Format: 1:1 video or voice
- Recording: ask permission first
- Interview stance: neutral and quiet after each question
- Do not pitch AgentFlow during the discovery blocks

### Questions (in order)

**Block 1: Current pain (5 min)**

1. Tell me about the last time one of your agents gave a wrong, stale, or incomplete answer because the underlying business data was off.
2. What was the agent trying to do, and which systems did it need data from in that moment?
3. How did you discover the answer was wrong, and what happened next?
4. What was the real cost of that failure?

**Block 2: Technical constraints (7 min)**

5. For the workflows you care about most, what freshness window is actually acceptable?
6. What response time does an answer need to feel usable in the workflow?
7. What keeps you from exposing live systems directly to agents today?
8. Where do current solutions break first: auth, rate limits, schema drift, joins, tool selection, observability, or something else?

**Block 3: Integration reality (7 min)**

9. How are your agents built today: LangChain, LangGraph, LlamaIndex, custom code, vendor-native agents, or some combination?
10. How do those agents get operational data right now?
11. When a schema or upstream source changes, what usually breaks first in the agent path?
12. Which tasks need structured entities and metrics, and which ones are fine with free-text retrieval?
13. If you had to onboard a new data source for an agent this week, what would the work actually look like?

**Block 4: Buying signals (6 min)**

14. Who feels this pain most acutely, and who would decide whether to solve it?
15. What would need to be true for your team to run a pilot in the next 30-60 days?
16. If you were evaluating solutions, which products or approaches would make your shortlist first?
17. What would make you reject a solution quickly, even if the demo looked good?

**Block 5: Willingness-to-pay probes (5 min)**

18. What are you already spending today in engineering time, vendor spend, or platform complexity to make agent data access work?
19. If a solution removed custom tool/API glue work, what budget or headcount would it realistically replace?
20. Which capability would be valuable enough that you would pay materially more for it?
21. How would you expect this category to be priced so that it feels natural to buy?

### Probe lines when answers are vague

- "Walk me through the last concrete example."
- "How often does that happen?"
- "Who had to get pulled in?"
- "What did you try before?"
- "Why is that still not good enough?"

### Questions to avoid

- "Would you use AgentFlow if it had X?"
- "You need sub-30-second freshness, right?"
- "Would an MCP server solve this?"
- "Do you want a LangChain integration?"

These create false positives and bias the interview toward validation theater.

### Optional concept test for the final 2-3 minutes

Only use this if the interview already exposed a real pain:

"Imagine a small serving layer for agents that exposes typed business entities and metrics, includes explicit freshness metadata, and plugs into agent runtimes through SDKs or MCP. What part sounds most useful, and what part sounds unnecessary?"

Follow-up probes:

- "What would you compare that to first?"
- "What would have to be proven in week one?"
- "What would make this feel risky?"

### After-interview template

| Interviewee | Role | Company stage | Agent stack | Top pain | Current workaround | Freshness requirement | Buyer signal | WTP signal | Next step |
|-------------|------|---------------|-------------|----------|--------------------|----------------------|-------------|-----------|----------|
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

### Red flags

- If 3+ of 5 interviews say an existing vendor like Tinybird, Supabase, Neon, or MotherDuck already covers the operational need well enough, v1.1 should not assume differentiation on integration alone.
- If nobody describes freshness or trust in data as a top operational risk, the current wedge is weak or premature.
- If teams mostly want one generic query tool and do not care about typed entities/metrics, contract-first positioning may be weaker than assumed.
- If promising teams cluster in one framework ecosystem, a broad framework strategy can wait and prioritization becomes clearer.

## 4. v1.1 Recommendation

### Top-3 priorities (ranked)

1. **Read-first MCP surface**: ship a small remote MCP server with 5-8 high-value read tools, auth scoping, read-only semantics, and freshness metadata on every meaningful response. This is the broadest ecosystem move and best matches current market direction. Estimated effort: `medium`.
2. **Thin LangChain/LangGraph integration over the same contract**: keep a first-class toolkit for teams already in LangChain, but make it a thin adapter over the same underlying entities/metrics/freshness contract instead of a separate product branch. Estimated effort: `small/medium`.
3. **Freshness and contract semantics as product primitives**: make `as_of`, freshness windows, staleness policy, and contract versioning/changelog visible in SDK and MCP responses. This is where AgentFlow can actually differentiate from generic database or analytics surfaces. Estimated effort: `medium`.

### Why this ranking

- Priority 1 maximizes distribution and reduces framework-fragmentation risk.
- Priority 2 meets the most likely framework-specific demand without overcommitting to multiple custom adapters.
- Priority 3 sharpens the product wedge; without it, MCP or LangChain support alone is not durable differentiation.

### Anti-priorities (what not to do in v1.1)

- Do not lead with generic NL-to-SQL as the main story.
- Do not build write-capable MCP actions before interviews prove demand and risk tolerance.
- Do not expand to a large tool catalog before evals show the minimal tool set is working.
- Do not invest heavily in LlamaIndex-specific features before the core MCP plus LangChain plus freshness story is validated.
- Do not collapse the typed SDK/API surface into MCP-only access.

### Before commit needed data

- 5 customer interviews using the script above
- If possible, demo telemetry on:
  - p95 entity read latency
  - p95 metric read latency
  - freshness breach rate
  - time to first working agent answer
  - percentage of questions needing multi-source context assembly

### Decision gates after first interview batch

- If interviews validate freshness + custom glue pain strongly, continue with MCP plus LangChain plus freshness primitives.
- If interviews say existing vendor MCP/database tooling is already good enough, narrow the wedge further around contracts, observability, or multi-source serving.
- If interviews show mostly one framework ecosystem, compress the roadmap and support that framework first.

## 5. Sources

- https://docs.langchain.com/oss/python/langchain/tools (checked 2026-04-20)
- https://docs.langchain.com/oss/python/integrations/tools/sql_database/ (checked 2026-04-20)
- https://docs.langchain.com/oss/python/langchain/mcp (checked 2026-04-20)
- https://developers.llamaindex.ai/python/framework/ (checked 2026-04-20)
- https://developers.llamaindex.ai/python/framework/module_guides/indexing/vector_store_index/ (checked 2026-04-20)
- https://developers.llamaindex.ai/python/framework/module_guides/indexing/document_management/ (checked 2026-04-20)
- https://modelcontextprotocol.io/introduction (checked 2026-04-20)
- https://modelcontextprotocol.io/docs/concepts/architecture (checked 2026-04-20)
- https://modelcontextprotocol.io/blog/2025-12-09-mcp-aaf (checked 2026-04-20)
- https://developers.openai.com/api/docs/guides/function-calling (checked 2026-04-20)
- https://developers.openai.com/api/docs/guides/migrate-to-responses (checked 2026-04-20)
- https://developers.openai.com/api/docs/mcp (checked 2026-04-20)
- https://developers.openai.com/cookbook/examples/o-series/o3o4-mini_prompting_guide (checked 2026-04-20)
- https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use (checked 2026-04-20)
- https://docs.anthropic.com/en/docs/agents-and-tools/mcp (checked 2026-04-20)
- https://www.tinybird.co/docs/forward/analytics-agents (checked 2026-04-20)
- https://www.tinybird.co/docs/forward/analytics-agents/mcp (checked 2026-04-20)
- https://www.tinybird.co/pricing (checked 2026-04-20)
- https://materialize.com/ (checked 2026-04-20)
- https://materialize.com/docs/integrations/model-context-protocol-mcp/ (checked 2026-04-20)
- https://materialize.com/pricing/ (checked 2026-04-20)
- https://neon.com/docs/use-cases/ai/neon-for-ai-tools (checked 2026-04-20)
- https://neon.com/blog/three-ways-to-use-neon-for-building-ai-agents (checked 2026-04-20)
- https://neon.com/blog/xpander-ai-agents-slack-neon-backend (checked 2026-04-20)
- https://supabase.com/docs/guides/getting-started/mcp (checked 2026-04-20)
- https://supabase.com/docs/guides/getting-started/self-hosted/local-development/access-your-mcp-server (checked 2026-04-20)
- https://supabase.com/docs/guides/getting-started/mcp#security-risks (checked 2026-04-20)
- https://motherduck.com/docs/integrations/ai/mcp-server/ (checked 2026-04-20)
- https://motherduck.com/docs/integrations/ai/langchain/ (checked 2026-04-20)
- https://motherduck.com/product/pricing/ (checked 2026-04-20)
- https://vercel.com/docs/mcp (checked 2026-04-20)
- https://vercel.com/docs/agent-tools (checked 2026-04-20)
- https://vercel.com/docs/postgres (checked 2026-04-20)
- https://openai.com/index/openai-acquires-rockset/ (checked 2026-04-20)
- https://github.com/langchain-ai/langchain/pull/35459 (checked 2026-04-20)
- https://github.com/langchain-ai/langchain/issues/35872 (checked 2026-04-20)
- https://github.com/run-llama/llama_index/issues/21378 (checked 2026-04-20)
- https://github.com/run-llama/llama_index/issues/21413 (checked 2026-04-20)

## Notes on uncertainty

- Where I say "no first-party page found," that is an inference from focused public-doc review as of 2026-04-20, not proof of product nonexistence.
- Where a public product surface no longer exists, I marked it as historical or `[UNCLEAR from public docs]` rather than forcing a stronger claim.
