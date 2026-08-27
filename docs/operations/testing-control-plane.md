# Testing the control plane

The PostgreSQL control-plane adapters are where the port's hard promises live:
a webhook enqueue that exactly one replica may win, claims taken with
`FOR UPDATE SKIP LOCKED` under a lease, the outbox↔dead-letter flip that has to
happen in one transaction or not at all. A regression in any of them is quiet —
no exception, no failing request, just an event delivered twice or lost — which
is why they get a coverage floor of their own rather than sharing the
repository-wide one.

## Why unit-only coverage misleads here

Audit F-12 measured nine modules at 18–46% and correctly declined to read that
as "untested". Two different things were hiding under one number, and they need
opposite fixes.

For most of them the number was a **measurement artifact**: their branches only
execute against a real server or through the API, so a unit-only figure
measures the absence of a database, not the absence of tests. Counting the live
and API-level suites changes the picture completely. For one — the embedded
analytics repository, which backs the *default* profile — it was **real debt**,
and the fix was writing the tests.

| Module | As audited | Now | Floor | Why it moved |
| --- | ---: | ---: | ---: | --- |
| `routers/ops.py` | 29% | 98% | 90 | counted the ops integration suites |
| `postgres_outbox_replay.py` | 18% | 99% | 95 | live suite + new inbox/triage parity probes |
| `postgres_alert.py` | 27% | 95% | 90 | counted the live suite |
| `postgres_base.py` | 42% | 93% | 88 | counted the live suite |
| `embedded_usage_audit.py` | 46% | 92% | 85 | **new tests** — analytics reads, batching, lock retries |
| `postgres_usage_audit.py` | 21% | 87% | 82 | live suite + F-18 retention probes |
| `reconciliation.py` | 22% | 87% | 80 | counted the ops integration suites |
| `postgres.py` (assembly) | — | 82% | 78 | counted the live suite |
| `postgres_webhook.py` | 24% | 80% | 75 | counted the live suite |
| `node/ingest.py` | 24% | 100% | 95 | counted the node-topology integration file + **new tests** — bearer ladder, dead-letter accounting, filter scope |

Measured 2026-08-25 against PostgreSQL 14.24 with the commands below. Floors
sit a few points under the measured value: they are a ratchet against
regression, not a target to code to. Raise one when the real number moves up
and stays there; never lower one to turn a build green without saying why in
the commit that does it.

`node/ingest.py` — the center's `POST /v1/node/events` federation endpoint — was
the last one in, and turned out to be mostly the artifact again: the handoff
that called its bearer auth, off-center 404, batch bound and idempotency filter
"unexercised" was reading a number that did not count
`tests/integration/test_node_topology.py`, which drives all four through the
booted app and reaches 98% of the module on its own. The remaining two lines
(a non-bearer `Authorization` scheme, the dead-letter branch of the apply loop)
and the contracts the topology file pins only implicitly — the 401-vs-403
ladder, a center whose token is unset, dead-lettered ids as duplicates on
retry, duplicates *within* one batch, events without an id, the two-topic scope
of the check-then-act filter — are `tests/unit/test_node_ingest.py`, against a
minimal app so a 401 there comes from the router's own ladder and nothing else.
Writing them found one defect: a `source_metadata` that was not a mapping
skipped the branch tag while the event still applied, so the journal row
carried no branch and the cross-branch view never saw it. The stamp
(`serving/node/stamp.py`, shared with the edge emitter) now replaces the
unusable value — except on a CDC-shaped event, whose `source_metadata` is
schema-owned provenance and is left for the validator to reject.

`scripts/check_control_plane_coverage.py` holds the table and is the gate. A
module with **no** coverage data fails it as 0% on purpose: the usual reason a
critical module goes unmeasured is that the live tests skipped themselves for
want of a DSN, and a gate that passes when its evidence is missing is not a
gate.

## Running the live suite locally

`tests/integration/test_control_plane_postgres_live.py` skips itself unless
`AGENTFLOW_TEST_PG_DSN` points at a reachable server. Any PostgreSQL will do —
a container, a managed instance, or a throwaway cluster from the server
binaries you already have:

```bash
PGBIN=/usr/lib/postgresql/14/bin          # or wherever initdb/pg_ctl live
PGDATA=$HOME/agentflow-pg-test
"$PGBIN/initdb" -D "$PGDATA" -U agentflow --auth=trust -E UTF8
{
  echo "listen_addresses = '127.0.0.1'"
  echo "port = 55432"
  echo "unix_socket_directories = '$PGDATA'"   # the packaged default is root-owned
} >> "$PGDATA/postgresql.conf"
"$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" -w start
"$PGBIN/createdb" -h 127.0.0.1 -p 55432 -U agentflow agentflow
```

Then:

```bash
export AGENTFLOW_TEST_PG_DSN=postgresql://agentflow@127.0.0.1:55432/agentflow
pytest tests/integration/test_control_plane_postgres_live.py -q
```

**Use `127.0.0.1`, not `localhost`.** Where the server is reached through a
port forward — a WSL2 distro from Windows, for instance — `localhost` resolves
to `::1` first and each connection pays the IPv6 timeout before falling back.
Single connections merely feel slow; the store's pool gives up entirely,
because every worker spends longer connecting than the pool's own open timeout
allows, and the failure surfaces as `PoolTimeout: couldn't get a connection`
with nothing about DNS in it.

The suite truncates its tables between tests, so point it at a database you are
willing to have emptied. `pg_ctl -D "$PGDATA" stop` when you are done; the data
directory is disposable.

## Measuring the critical set

Unit and live coverage go into one data file, for the reason at the top:

```bash
coverage erase
coverage run --append -m pytest -q -p no:cov \
  tests/unit/test_control_plane_store.py \
  tests/unit/test_control_plane_capabilities.py \
  tests/unit/test_postgres_enqueue_lease_contract.py \
  tests/unit/test_query_analytics_retention.py \
  tests/unit/test_analytics_middleware.py \
  tests/unit/test_embedded_usage_analytics.py \
  tests/unit/test_audit_publisher.py \
  tests/unit/test_usage_db_connection_reuse.py \
  tests/unit/test_usage_write_off_request_path.py \
  tests/unit/test_node_ingest.py
coverage run --append -m pytest -q -p no:cov \
  tests/integration/test_control_plane_postgres_live.py \
  tests/integration/test_exceptions_inbox.py \
  tests/integration/test_stuck_orders.py \
  tests/integration/test_tenant_isolation.py \
  tests/integration/test_node_topology.py
python scripts/check_control_plane_coverage.py
```

Only the first integration file needs the server; the other four drive the API
over DuckDB and run anywhere. `-p no:cov` keeps pytest-cov from
double-instrumenting the `coverage run` — the same pattern the auth and outbox
gates use.

CI runs exactly this in the `test-integration` job against its `postgres:17`
service, and publishes `coverage-control-plane.xml` as a build artifact. It is
deliberately separate from the repository-wide report: folding integration
coverage into the general floor would raise the aggregate without covering
anything new, which is the arithmetic F-12 objected to.

## What this does not prove

- **The local recipe is not the CI engine.** The numbers above come from
  PostgreSQL 14.24; CI runs `postgres:17`. Nothing in the adapter is
  version-specific as far as the suite reaches, but a floor met on 14 is
  evidence about 14.
- **Coverage instrumentation changes the timing.** Under `coverage run` the
  live suite takes roughly five times as long on a workstation, and the
  threaded probes (pool bounds, parallel claims, lease expiry) are the ones
  that notice. One instrumented run on Windows was seen to hang and one to fail
  a timing assertion; neither reproduced. Treat a single red run of those
  probes as suspect before treating it as a regression — and never as green
  noise if it repeats.
- **A floor is not a proof of correctness.** 98% of `ops.py` executing says
  those lines ran, not that the triage semantics behind them are right. What
  pins those is the parity sweep in the live suite, which mirrors the embedded
  adapter's unit expectations one for one so the two cannot drift.
- **`node/ingest.py` at 100% is line coverage of a thin router.** Its hard
  part — the check-then-act idempotency filter — is safe only because
  `SERVING_WRITE_LOCK` serialises every ingest write within the single center
  process. The tests pin the filter's scope and its accounting, not a
  concurrent multi-center writer, which the module's own n4 note says does not
  exist yet.
