# Generated External Gate Pack - 2026-05-30

## Boundary

This pack is generated/modelled material. It is useful for planning, rehearsal,
sales-readiness drafts, and deciding what real evidence must be collected later.
It is not external evidence and must not be used to mark release-readiness gates
complete.

No AWS account, paid service, Docker workload, production system, customer data,
security scan, or real benchmark was used to create this pack. Do not publish
any generated record below as a real customer interview, real production CDC
onboarding, real benchmark, or real external pen-test attestation.

## Generated Coverage Matrix

| Gate | Generated material in this pack | Real gate status |
|------|---------------------------------|------------------|
| AWS/Terraform apply | Zero-budget not-applicable decision note | Not planned unless explicitly reintroduced with budget and owner approval |
| Production CDC | Synthetic decision record and first-run rehearsal | Blocked for real production source evidence |
| PMF/customer discovery | Five generated interview records, scorecard, and segment synthesis | Blocked for real replies/interviews/customer evidence |
| Pricing/WTP | Generated pricing-signal review and pilot-shape rehearsal | Blocked for real WTP/LOI/invoice/procurement evidence |
| Production hardware benchmark | Synthetic benchmark scenario and report shape | Blocked for approved hardware, run transcript, and raw results |
| External pen test | Simulated attestation packet and remediation map rehearsal | Blocked for third-party report or signed attestation |

## Zero-Budget AWS/Terraform Decision Note

AWS/Terraform apply is not part of the current zero-budget path. The generated
decision for this project is:

| Field | Generated decision |
|-------|--------------------|
| Cloud spend | Not approved |
| Paid managed-cloud dependency | Avoided |
| Terraform apply | Not planned |
| Release posture | Local/CI evidence only; no AWS production claim |
| Reopen condition | Operator explicitly reintroduces AWS with budget, account owner, role ARN, tfvars owner, and apply approval |

Generated implication: all AWS OIDC/Terraform material remains a runbook and
does not drive the current product path.

## Synthetic Production CDC Decision Record

This is a rehearsal record for the shape of a future production CDC intake. It
does not describe a real production source.

| Field | Generated value |
|-------|-----------------|
| Source owner | Synthetic SupportOps platform owner |
| Secret owner | Synthetic platform security owner |
| Source engine | PostgreSQL 15 |
| Hostname and port | `synthetic-supportops-postgres.internal:5432` |
| Database name | `supportops` |
| Table scope | `public.accounts`, `public.subscriptions`, `public.support_cases`, `public.entitlements` |
| Data classification | Operational + customer account metadata; PII redaction required |
| Initial snapshot policy | Schema-only start, then incremental snapshot during maintenance window |
| Maintenance window | Sunday 02:00-04:00 local time |
| Network path | Private service network only |
| Kafka Connect Secret | `agentflow-cdc-supportops` in `agentflow-prod` |
| Monitoring owner | Synthetic data platform on-call |
| Rollback owner | Synthetic platform lead |

Generated first-run rehearsal:

| Check | Generated result |
|-------|------------------|
| Connector status | `RUNNING` for one connector with two tasks |
| Raw topics | `cdc.supportops.public.accounts`, `cdc.supportops.public.subscriptions`, `cdc.supportops.public.support_cases`, `cdc.supportops.public.entitlements` |
| Heartbeat topic | `cdc.supportops.heartbeat` |
| Normalized event shape | `entity_type=account`, `entity_id=acct_1001`, `tenant_id=synthetic-acme`, `freshness_lag_ms=1840` |
| Dead letters | `0` in the generated first hour |
| Rollback trigger | lag over 120 seconds for 10 minutes or any PII-redaction failure |

Synthetic CDC risk read:

| Risk | Generated mitigation |
|------|----------------------|
| Wildcard table scope creep | Explicit allowlist only |
| CDC credential overreach | Table-scoped read/replication grants |
| Snapshot load | Schema-only start plus incremental backfill |
| Tenant leakage | Normalizer pins tenant id and redaction policy before serving |
| Operational ownership | Monitoring and rollback owners named before connector creation |

## Generated PMF Interviews

These records are generated from the existing discovery script and public
segment hypotheses. They are not real interviews.

### Interview 1 - Support Operations

| Field | Generated record |
|-------|------------------|
| Role | Head of Support Operations |
| Company stage/size | Mid-market B2B SaaS, 300-800 employees |
| Workflow discussed | AI support agent answers account/subscription questions |
| Last concrete failure | Agent gave a nearly correct subscription answer but missed a recently approved entitlement exception |
| Systems involved | Helpdesk, CRM, billing, entitlement service |
| Current data path | Helpdesk macro plus nightly billing export and manual escalation notes |
| Freshness requirement by workflow | Entitlements must be under 5 minutes old before answer is trusted |
| Main blocker today | Exceptions and escalation rules live outside the agent-visible context |
| Current workaround | Human review for any account-state or plan-change answer |
| Security/governance concern | Agent should not get broad billing-console access |
| Mentioned alternatives | Helpdesk-native AI, internal API wrapper, manual QA queue |
| Strongest buying signal | Reducing repeat handling and unsafe escalations |
| Strongest rejection signal | If the setup requires another broad integration project |
| Budget owner | Support operations with platform approval |
| Replaceable cost | QA/reopen handling and custom integration maintenance |
| Natural value metric reaction | Workflow or served entity feels more natural than request volume |
| Pilot shape | Read-only account context for one support queue for 30 days |
| Pricing risk | Usage pricing feels unpredictable during support spikes |
| Generated quote | "The problem is not that the answer is always wrong; it is that the agent cannot prove when it is safe." |

Score: pain `2`, freshness `2`, glue burden `2`, ownership `2`, pilot readiness
`2`, budget/WTP `1`, governance `2`, total `13`.

### Interview 2 - Data Platform

| Field | Generated record |
|-------|------------------|
| Role | Data/platform engineering lead |
| Company stage/size | AI-native B2B product, 100-300 employees |
| Workflow discussed | Product agent reads and writes CRM/account state |
| Last concrete failure | Agent proposed a renewal-risk update while CRM and billing disagreed on account status |
| Systems involved | CRM, billing, product telemetry, warehouse, internal API |
| Current data path | Warehouse models plus hand-built service endpoints |
| Freshness requirement by workflow | Writes require source-priority proof and sub-minute source timestamps |
| Main blocker today | No canonical rule for source priority when systems conflict |
| Current workaround | Read-only mode and manual write approval |
| Security/governance concern | Write access needs field-level scope and audit trail |
| Mentioned alternatives | Internal read model, reverse ETL, workflow-specific API |
| Strongest buying signal | Safe write path depends on provenance, not just faster sync |
| Strongest rejection signal | If AgentFlow duplicates warehouse ownership |
| Budget owner | Platform engineering |
| Replaceable cost | Two engineers maintaining source-specific glue |
| Natural value metric reaction | Served entity/contract is the clearest value unit |
| Pilot shape | One account entity, two sources, read-only then reviewed writes |
| Pricing risk | Connector-count pricing punishes normal source sprawl |
| Generated quote | "Fresh data is table stakes; the missing piece is a contract that says which truth wins." |

Score: pain `3`, freshness `3`, glue burden `3`, ownership `3`, pilot readiness
`2`, budget/WTP `2`, governance `2`, total `18`.

### Interview 3 - RevOps/CS Ops

| Field | Generated record |
|-------|------------------|
| Role | Revenue operations owner |
| Company stage/size | B2B SaaS, 150-500 employees |
| Workflow discussed | AI account intelligence for renewal and expansion workflows |
| Last concrete failure | Account summary omitted a recent workflow change and sent CSMs toward the wrong follow-up |
| Systems involved | Salesforce, support tickets, meeting notes, product analytics |
| Current data path | Salesforce reports, docs, and ad hoc spreadsheet exports |
| Freshness requirement by workflow | Same-day freshness is enough for summaries; minutes matter for open support escalations |
| Main blocker today | Users cannot inspect why one account signal was selected |
| Current workaround | CSMs verify account summaries manually before action |
| Security/governance concern | Account data crosses CS, sales, and support permissions |
| Mentioned alternatives | Salesforce-native AI, BI dashboard, internal analyst workflow |
| Strongest buying signal | Better signal provenance could reduce manual account prep |
| Strongest rejection signal | If actionability stays weaker than current dashboards |
| Budget owner | RevOps with CS leadership |
| Replaceable cost | Manual prep time and missed renewal-risk signals |
| Natural value metric reaction | Workspace/environment is understandable if multiple teams share it |
| Pilot shape | One renewal-risk workflow with provenance fields visible |
| Pricing risk | Seat pricing misaligns with shared operations workflows |
| Generated quote | "The summary is only useful if the CSM can see what changed and who owns the next action." |

Score: pain `2`, freshness `2`, glue burden `2`, ownership `2`, pilot readiness
`2`, budget/WTP `1`, governance `2`, total `13`.

### Interview 4 - AI-Native Product Founder

| Field | Generated record |
|-------|------------------|
| Role | Founder/CTO |
| Company stage/size | Seed/Series A AI product |
| Workflow discussed | Customer-facing agent needs business context and customer-specific rules |
| Last concrete failure | Customer-specific policy exception required a bespoke workflow branch |
| Systems involved | Product database, CRM, customer config, support tool |
| Current data path | Custom per-customer code and internal tools |
| Freshness requirement by workflow | Minutes for account state; immediate validation for write actions |
| Main blocker today | Hard to separate reusable context contracts from services work |
| Current workaround | Customer-specific integration code |
| Security/governance concern | Customer data isolation and auditability |
| Mentioned alternatives | Build in-house, customer-specific service layer, workflow vendor |
| Strongest buying signal | Reducing bespoke integration burden |
| Strongest rejection signal | If the platform cannot handle customer-specific business logic |
| Budget owner | Product/engineering founder |
| Replaceable cost | Implementation time per enterprise customer |
| Natural value metric reaction | Pilot package is easier than usage pricing at this stage |
| Pilot shape | One customer workflow with typed context and audit trail |
| Pricing risk | Too much platform pricing before one customer problem is proven |
| Generated quote | "If this only moves glue from our code to your config, it is not enough." |

Score: pain `2`, freshness `2`, glue burden `3`, ownership `2`, pilot readiness
`2`, budget/WTP `2`, governance `1`, total `14`.

### Interview 5 - Security/Governance

| Field | Generated record |
|-------|------------------|
| Role | Security/platform reviewer |
| Company stage/size | Enterprise software company |
| Workflow discussed | Approval of agent access to operational systems |
| Last concrete failure | Pilot stalled because requested credential scope was broader than the use case |
| Systems involved | IAM, API gateway, audit logs, CRM, support platform |
| Current data path | Human service accounts and manual approval |
| Freshness requirement by workflow | Less important than least privilege and auditability |
| Main blocker today | No field-level proof of what the agent can read or write |
| Current workaround | Read-only exports or human-mediated actions |
| Security/governance concern | Non-human identity, revocation, prompt/tool misuse, audit completeness |
| Mentioned alternatives | Internal API gateway, secrets broker, no autonomous write access |
| Strongest buying signal | Field-scoped access and audit trail could unlock limited pilots |
| Strongest rejection signal | If the product asks for broad credentials or opaque tools |
| Budget owner | Platform/security, usually not line-of-business alone |
| Replaceable cost | Security review cycles and blocked pilot time |
| Natural value metric reaction | Environment/workspace packaging maps to governance ownership |
| Pilot shape | Read-only pilot with audit log and narrow credential scope |
| Pricing risk | Security buyers need predictable enterprise evaluation terms |
| Generated quote | "A narrow no is better than a broad yes we cannot defend." |

Score: pain `2`, freshness `1`, glue burden `2`, ownership `3`, pilot readiness
`1`, budget/WTP `1`, governance `3`, total `13`.

## Generated PMF Synthesis

| Question | Generated read |
|----------|----------------|
| Strongest segment | Data/platform engineering |
| Strongest wedge | Action-safety contracts for agents over operational entities |
| Clearest product language | "Typed context with freshness, source priority, and permission provenance" |
| Weakest assumption | Buyers may see this as bespoke integration work unless a narrow reusable contract is obvious |
| Anti-ICP signal | Teams that only need document retrieval or generic analytics |
| Generated scope implication | Keep v1.1 narrow: read-first context contracts, provenance, freshness metadata, and reviewed-write path |

Generated scorecard totals:

| Segment | Total | Read |
|---------|-------|------|
| Support operations | 13 | Concrete pain, pilot possible, budget weaker |
| Data/platform | 18 | Strongest modelled ICP |
| RevOps/CS Ops | 13 | Good workflow, provenance must be visible |
| AI-native product | 14 | Strong glue pain, services-collapse risk |
| Security/governance | 13 | Strong blocker, pilot readiness weaker |

## Generated Pricing/WTP Review

Generated pricing gates:

| Gate | Generated count | Generated read |
|------|-----------------|----------------|
| Interviews naming plausible budget owner | 5 / 5 | Modelled pass |
| Interviews naming replaceable cost | 5 / 5 | Modelled pass |
| Interviews describing credible paid pilot path | 5 / 5 | Modelled pass, but two are conditional |
| Interviews reacting to value metric | 5 / 5 | Modelled pass |

Generated pricing decision:

| Decision | Generated result |
|----------|------------------|
| Most natural first packaging | Founder-led paid pilot |
| Metric to test first | Served entity/contract plus environment scope |
| Metric to avoid first | Pure request-volume pricing |
| Pilot duration | 30-60 days |
| Pilot scope | One workflow, two to three operational sources, typed context, freshness/provenance, audit log |
| Buyer | Platform/data owner with workflow owner sponsor |
| Generated price-posture note | Do not publish self-serve tiers before real interviews; use pilot scoping language only |

Generated pilot package:

| Component | Generated offer shape |
|-----------|----------------------|
| Workflow | One agent workflow blocked by stale/split/unsafe operational context |
| Sources | Two to three approved operational sources |
| Deliverable | Typed entity contract, freshness metadata, source-priority rule, permission provenance, SDK/API/MCP serving surface |
| Success criteria | Lower manual verification, fewer unsafe escalations, clear audit trail, owner-approved context contract |
| Exclusions | No autonomous production write without reviewed-write controls |

## Synthetic Production-Hardware Benchmark Rehearsal

This is not a measured benchmark. It shows the report shape expected when a
real production-class host is available.

| Field | Generated rehearsal value |
|-------|---------------------------|
| Hardware class | Dedicated 16 vCPU / 32 GiB ARM64 or x86_64 host |
| Host label | `synthetic-prod-bench-01` |
| Commit | `8412a53` for rehearsal docs only |
| Data fixture | Synthetic support/account/order fixture; no production/customer data |
| API topology | Same private network as benchmark client |
| Warmup | 5 minutes |
| Measured window | 20 minutes |

Generated report table:

| Metric | Generated target | Evidence status |
|--------|------------------|-----------------|
| p50 read latency | under 150 ms | Not measured |
| p95 read latency | under 500 ms | Not measured |
| p99 read latency | under 900 ms | Not measured |
| Sustained request rate | 100 RPS | Not measured |
| Error rate | below 0.1% | Not measured |
| Freshness lag | under 30 seconds for benchmark fixture | Not measured |

Real publication remains blocked until raw JSON, command transcript, host
metadata, fixture-safety approval, and publication approval exist.

## Simulated External Pen-Test Attestation Packet

This is a rehearsal packet only. It is not a third-party pen-test report.

| Field | Generated value |
|-------|-----------------|
| Tester identity | Synthetic independent tester |
| Test scope | Public API, auth middleware, SDK clients, docs examples |
| Method | Gray-box authenticated and unauthenticated review |
| Test window | Generated scenario, no real dates |
| Severity summary | Critical 0, High 1, Medium 3, Low 5, Informational 4 |
| Report artifact | Not real |
| Retest status | Not real |
| Attestation owner | Not assigned |

Generated remediation map rehearsal:

| Synthetic finding | Severity | Expected evidence path |
|-------------------|----------|------------------------|
| Over-broad API key scope in sample workflow | High | Auth manager tests, security audit note, docs caveat |
| Missing rate-limit dashboard link | Medium | Runbook/dashboard update |
| Ambiguous tenant boundary wording in integration docs | Medium | Docs correction and tenant test references |
| Incomplete dependency-scan evidence packet | Medium | Security workflow artifact and quality report output |
| Security questionnaire lacks external-attestation boundary | Low | External pen-test handoff update |

Real attestation remains blocked until an external tester, scope, report,
severity summary, remediation map, and retest/attestation artifact exist.

## Generated Acceptance Boundary

| Gate | Generated pack status | Real evidence count |
|------|-----------------------|---------------------|
| Production CDC | Generated rehearsal complete | 0 |
| PMF interviews | Generated five-record batch complete | 0 real interviews |
| Pricing/WTP | Generated review complete | 0 real WTP artifacts |
| Benchmark | Generated report shape complete | 0 real production-hardware runs |
| External pen test | Generated attestation rehearsal complete | 0 real third-party reports |

Use this pack to avoid blank handoffs. Do not use it to claim external evidence.
