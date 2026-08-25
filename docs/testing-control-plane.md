# Testing the control plane

The PostgreSQL control-plane adapters are where the port's hard promises live:
a webhook enqueue that exactly one replica may win, claims taken with
`FOR UPDATE SKIP LOCKED` under a lease, the outbox↔dead-letter flip that has to
happen in one transaction or not at all. A regression in any of them is quiet —
no exception, no failing request, just an event delivered twice or lost — which
is why they get a coverage floor of their own rather than sharing the
repository-wide one.

## Why unit-only coverage misleads here

Audit F-12 measured these modules at 18–27% and correctly declined to read that
as "untested": most of their branches only execute against a real server, so a
unit-only number measures the absence of a database, not the absence of tests.
Counting the live suite changes the picture completely:

| Module | Unit only | Unit + live | Floor |
| --- | ---: | ---: | ---: |
| `postgres_outbox_replay.py` | 21% | 99% | 95 |
| `postgres_alert.py` | 32% | 95% | 90 |
| `postgres_base.py` | 50% | 93% | 88 |
| `postgres_usage_audit.py` | 23% | 87% | 82 |
| `postgres.py` (assembly) | 82% | 82% | 78 |
| `postgres_webhook.py` | 27% | 80% | 75 |

Measured 2026-08-25 against PostgreSQL 14.24 with the commands below. Floors
sit a few points under the measured value: they are a ratchet against
regression, not a target to code to. Raise one when the real number moves up
and stays there; never lower one to turn a build green without saying why in
the commit that does it.

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
rather than anything mentioning DNS.

The suite truncates its tables between tests, so point it at a database you are
willing to have emptied.

## Measuring the critical set

Unit and live coverage go into one data file, for the reason at the top:

```bash
coverage erase
coverage run --append -m pytest -q -p no:cov \
  tests/unit/test_control_plane_store.py \
  tests/unit/test_control_plane_capabilities.py \
  tests/unit/test_postgres_enqueue_lease_contract.py \
  tests/unit/test_query_analytics_retention.py \
  tests/unit/test_analytics_middleware.py
coverage run --append -m pytest -q -p no:cov \
  tests/integration/test_control_plane_postgres_live.py
python scripts/check_control_plane_coverage.py
```

`-p no:cov` keeps pytest-cov from double-instrumenting the `coverage run` —
the same pattern the auth and outbox gates use.

CI runs exactly this in the `test-integration` job against its `postgres:17`
service, and publishes `coverage-control-plane.xml` as a build artifact.
It is deliberately separate from the repository-wide report: folding
integration coverage into the general floor would raise the aggregate without
covering anything new, which is the arithmetic F-12 objected to.

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
- **The critical set is the PostgreSQL adapter, not the whole control plane.**
  The embedded adapter's analytics repository, the `/v1/ops` router,
  `semantic_layer/reconciliation.py` and `node/ingest.py` were named by the
  same finding and still have no floor of their own.
