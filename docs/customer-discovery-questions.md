# AgentFlow Customer Discovery Questions

**Date**: 2026-04-20  
**Goal**: validate whether live operational data access is a painful enough problem to justify AgentFlow v1.1  
**Format**: 30-minute founder-led interview script  
**Rule**: this is a discovery script, not a sales deck

## What this script is trying to learn

- Did the team experience a recent, concrete failure from stale, split, missing, or unsafe data in an agent workflow?
- Is the pain really about freshness, or is freshness just one part of a larger trust/glue/governance problem?
- How does the team get operational data into agents today?
- Who owns the current workaround, and how painful is it to maintain?
- Is there enough pain and organizational clarity to justify a pilot in the next 30-60 days?

## Interviewer operating rules

- Ask for the last concrete failure within the first five minutes.
- Stay on one thread until you understand what actually happened.
- Ask "what happened next?" whenever the answer stays abstract.
- Do not introduce AgentFlow, MCP, LangChain, or "real-time data platform" language early.
- Do not rescue the interviewee with examples too soon.
- Treat silence as useful; wait after important questions.
- Capture exact phrases around trust, risk, and maintenance burden.
- Separate "wrong answer" into at least one of:
  - stale data
  - split-source entity
  - unsafe or over-broad access
  - schema/change-management breakage
  - brittle glue or orchestration

## Timekeeping

| Segment | Time | Objective |
|---------|------|-----------|
| Intro | 2 min | Set context, permission to take notes/record |
| Block 1: Failure story | 6 min | Get one concrete incident |
| Block 2: Current data path | 6 min | Understand freshness, sources, and boundaries |
| Block 3: Integration reality | 7 min | Surface change-management and workflow pain |
| Block 4: Buying motion | 5 min | Learn blockers, reject criteria, pilot shape |
| Block 5: WTP/prioritization | 4 min | Learn budget logic and tradeoffs |

## Intro script

"Thanks for making time. I'm researching how teams get live business data into agent workflows and where things break in practice. This is not a sales call. I'm mostly trying to understand what you've already tried, what failed, and what would actually have to be true for a better approach to matter. With your permission, I'll take notes as we go."

## Block 1: Last Concrete Failure (6 min)

**Objective:** force the conversation into a real example before the interview drifts into opinions.

### Main questions

1. Tell me about the last time an agent gave a wrong, stale, incomplete, or unsafe answer because the underlying business data path was off.
2. What was the agent trying to do in that moment?
3. Which systems or data sources were involved?
4. How did the team realize the answer was wrong?
5. What happened next in the workflow after the failure was discovered?

### Follow-up probes

- "Was the issue stale data, a missing join, a bad permission boundary, or something else?"
- "How old was the wrong data, roughly, when the answer was given?"
- "Who had to get pulled in to debug it?"
- "How often does this kind of failure happen?"
- "If nobody had caught it, what would the real damage have been?"

### Interviewer notes

- If the interviewee cannot recall a specific incident, that is signal.
- If they answer with "we haven't had that issue," ask for the last near-miss or the path they distrust most.
- If they jump to product wishes, pull them back to the incident timeline.

## Block 2: Current Data Path and Freshness Reality (6 min)

**Objective:** understand how the workflow actually gets data today and where freshness matters by domain.

### Main questions

1. If you trace that workflow today, where does the agent get its data from end to end?
2. Which parts of that path are live, which are staged or cached, and which are manually curated?
3. In that workflow, how fresh does the answer need to be before someone calls it wrong or unusable?
4. Where do you intentionally avoid exposing live systems directly to agents?

### Follow-up probes

- "Which part of the path makes you the least comfortable?"
- "Is the freshness requirement the same for every field, or does it vary by entity or action?"
- "Do users see timestamps or confidence/freshness cues today?"
- "If the answer is five minutes old, is that okay, annoying, or unacceptable?"
- "What is the current fallback when the live path is unavailable or risky?"

### Interviewer notes

- Avoid abstract SLA talk unless the interviewee already thinks that way.
- Use the last failure from Block 1 to ground the timing questions.
- Listen for different freshness contracts by workflow rather than a single global requirement.

## Block 3: Integration Reality and Change Management (7 min)

**Objective:** uncover the operational tax behind agent data access.

### Main questions

1. How are your agents built today: custom code, framework, vendor-native tooling, or some mix?
2. How do those agents get operational data right now?
3. When an upstream schema, API, or workflow changes, what usually breaks first in the agent path?
4. If you had to onboard a new data source for an agent this week, what work would actually happen?
5. Which tasks need structured entities and metrics, and which are fine with free-text retrieval or summaries?

### Follow-up probes

- "Who owns the safe serving boundary today?"
- "What part of this is custom glue that nobody wants to maintain?"
- "Where do you already have internal read models, curated views, or hand-built tools?"
- "What kind of debugging or tracing do you have when an answer is wrong?"
- "Does protocol choice matter much here, or is the problem elsewhere?"

### Interviewer notes

- This is the block where the real category usually appears.
- Many teams will describe the problem as "glue," "workarounds," "our internal API mess," or "security review pain" instead of "freshness."
- Do not force them into your preferred terminology.

## Block 4: Buying Motion and Reject Criteria (5 min)

**Objective:** find out whether the pain can become a real pilot, not just a nice-to-have.

### Main questions

1. Who inside the company feels this pain most acutely?
2. What would need to be true for your team to run a pilot in the next 30-60 days?
3. What would make you reject a solution quickly, even if the demo looked good?
4. Who can block the pilot even if the day-to-day users want it?

### Follow-up probes

- "Would this be evaluated by engineering, platform, security, procurement, or some mix?"
- "Would you compare this to an existing vendor, an internal build, or doing nothing?"
- "Is the blocker mostly technical, organizational, or budget-related?"
- "What evidence would you need in week one to keep paying attention?"

### Interviewer notes

- "Doing nothing" is a real competitor; do not ignore it.
- If they say "security," ask what exact review or concern usually kills momentum.
- If they say "we could build this," ask what that build would cost in real team time.

## Block 5: Willingness to Pay and Priority Shape (4 min)

**Objective:** learn how the problem would be budgeted and what capability carries actual value.

### Main questions

1. What are you already spending today in engineering time, vendor spend, platform complexity, or slower rollout velocity to make this work?
2. If nothing changes in the next quarter, what gets worse?
3. Which capability would be valuable enough that you would pay materially more for it?
4. If this worked, which budget, headcount, or internal project would it realistically replace?

### Follow-up probes

- "Would this be a team productivity purchase or a product-reliability purchase?"
- "Would predictable pricing matter more than raw cost?"
- "Is this a problem with an owner and budget, or just a recurring annoyance?"
- "What pricing shape would feel natural: subscription, workload, seats, environment, something else?"

### Interviewer notes

- Avoid asking for a fake budget number too early.
- The useful answer is often "which bucket would this come from?" not "would you pay $X?"
- Listen for whether they pay for trust, onboarding speed, governance leverage, or something else.

## Optional concept test for the last 2-3 minutes

Only use this if the interview already exposed a concrete pain.

"Let me sanity-check a concept. Imagine a read-first serving layer for agents that exposes typed business entities and metrics, includes explicit freshness metadata, and can plug into runtime surfaces like API, SDK, or MCP. What part of that sounds most useful, and what part sounds unnecessary?"

### Follow-up probes

- "What would you compare that to first?"
- "What would have to be proven in week one?"
- "Would protocol choice matter much compared with trust, setup time, and governance?"
- "What would make this feel risky?"

### Interviewer notes

- Do not ask this if the interview is still vague.
- Do not anchor on MCP unless the interviewee brings it up first.
- The goal is not validation theater; the goal is to hear what they strip out or reject.

## Questions to avoid

- "Would you use AgentFlow if it had X?"
- "You need sub-30-second freshness, right?"
- "Would MCP solve this?"
- "Do you want a LangChain integration?"
- "So the problem is really stale data?"

These create false positives or force the interviewee into your framing.

## Post-call note template

- Interviewee:
- Role:
- Company stage/size:
- Primary workflow discussed:
- Last concrete failure:
- Systems involved:
- Current data path:
- Freshness requirement by workflow:
- Main blocker today:
- Current workaround:
- Security/governance concern:
- Mentioned alternatives:
- Strongest buying signal:
- Strongest rejection signal:
- Exact quote worth keeping:
- Follow-up needed:

## Post-call scoring template

Score each dimension `0-3`.

| Dimension | 0 | 1 | 2 | 3 |
|-----------|---|---|---|---|
| Pain severity | no real pain | annoyance | recurring operational issue | expensive, urgent, trust-damaging pain |
| Freshness criticality | mostly irrelevant | nice-to-have | matters in some workflows | core requirement for high-value workflows |
| Glue/maintenance burden | simple today | some hacks | recurring custom upkeep | major cross-team maintenance tax |
| Ownership clarity | no owner | fuzzy owner | owner exists | clear owner plus escalation path |
| Pilot readiness | no timeline | vague interest | conditional pilot possible | clear 30-60 day pilot path |
| Budget/WTP signal | none | weak | plausible | explicit and strong |
| Governance pressure | none | light | meaningful | major blocker or purchase driver |

## How to interpret scores

- **Strong ICP candidate:** repeated concrete failures, visible workaround cost, clear owner, and at least a plausible pilot path.
- **Promising but not urgent:** real pain exists, but ownership or budget is still weak.
- **Low-priority segment:** mostly theoretical pain, low maintenance burden, or strong preference for staying with internal hacks.
- **Anti-ICP warning:** the team mainly wants document retrieval, generic NL-to-SQL, or realtime UI sync.

## Red flags from the first synthetic batch

- If the interviewee talks much more about governance than about speed, do not sell "real-time" as the headline.
- If they already have strong data infrastructure, do not pitch another data plane.
- If they are a tiny team with no budget owner, keep the conversation on setup and trust, not deep platform features.
- If they say protocol choice matters more than the business pain, the interview probably drifted too far into solutioning.
