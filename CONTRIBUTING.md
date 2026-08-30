# Contributing to AgentFlow

## Development setup

Use the Quick start in [README.md](README.md) and choose the setup script that matches your shell:

- PowerShell: `. .\scripts\setup.ps1`
- macOS / Linux: `source ./scripts/setup.sh`

Those scripts create the quick demo environment (`.[dev]` plus `./sdk`). For workflow-faithful installs, use the canonical dependency profiles declared in `pyproject.toml` under `[tool.agentflow.dependency-profiles]`:

| Profile | Install contract | Used by |
|---------|------------------|---------|
| `runtime` | `pip install -e .` | local serving/runtime-only paths |
| `dev-tools` | `pip install -e ".[dev]"` | `lint`, `schema-check`, host-side `e2e`, `staging`, `backup` |
| `test` | `pip install -e ".[dev,cloud]"` | `test-integration`, `chaos`, `mutation` |
| `test-integrations` | `pip install -e ".[dev,cloud]"` + `pip install -e "./sdk"` + `pip install -e "./integrations[mcp]"` | `test-unit`, local `make setup` |
| `load` | `pip install -e ".[load,cloud]"` | `load-test` |
| `perf` | `pip install -e ".[dev,load,cloud]"` | `perf-check`, `perf-baseline`, `perf-smoke` |
| `contract` | `pip install -e ".[dev,cloud,contract]"` | `contract` workflow |

For the fastest local loop, use `make demo`. For a production-shaped local stack with observability, use `make stack-prod-shaped-local` (a demo, not a production recipe -- see docs/deployment.md).

## Running tests

Release verification slice:

```bash
python -m pip install -e ".[dev,cloud]"
python -m pip install -e "./sdk"
python -m pip install -e "./integrations[mcp]"
python -m pytest tests/unit tests/integration tests/sdk -v
```

Additional suites when your change touches those areas:

```bash
python -m pip install -e ".[dev,cloud,contract]"
python -m pytest tests/contract tests/property tests/chaos tests/e2e -v
python -m pip install -e ".[dev,load,cloud]"
python scripts/run_benchmark.py
cd sdk-ts && npm test
```

The root `integrations` extra is intentionally not the repo test profile. Use `./integrations[mcp]` when you need LangChain, LlamaIndex, and MCP coverage together.

After the package-identity split, `pip show agentflow` refers to the Python SDK and `pip show agentflow-runtime` refers to the root runtime repo metadata.

## Before submitting a PR

1. Tests pass:

```bash
make test
```

2. Security diff is clean:

```bash
bandit -r src sdk --ini .bandit --severity-level medium -f json -o .tmp/bandit-current.json
python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
```

3. Benchmark does not regress past the release gate:

```bash
python scripts/run_benchmark.py
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current .artifacts/benchmark/current.json --max-regress 20
```

4. Contracts are still in sync:

```bash
python scripts/generate_contracts.py --check
python scripts/export_openapi.py --check
python scripts/export_sdk_capabilities.py --check
python scripts/export_quality_reference.py --check
```

After changing an API route or schema, run `python scripts/export_openapi.py`
and commit all three outputs (`docs/openapi.json` plus both files under
`docs/agent-tools/`). Do not edit one generated output independently.

After changing `[sdk]` claims or either public SDK client surface, run
`python scripts/export_sdk_capabilities.py` and commit
`docs/sdk-capabilities.md`. The `--check` form reproduces the tracked output;
the project-claims validator also checks that every declared method exists.

After changing `[quality]` claims, run
`python scripts/export_quality_reference.py` and commit `docs/quality.md`.
Host-specific reports belong to the ignored default output of
`python scripts/quality_report.py`; do not use that collector to overwrite the
tracked current reference.

`python scripts/profile_entity.py --entity-type <type> --entity-id <id>` writes
the quick entity-latency runtime result to ignored
`.artifacts/perf-smoke/entity-profile.json`. Relative outputs resolve from the
project root, and the harness refuses to write anywhere under `docs/perf/`.
Promote only a reviewed run under a new date-stamped identity with its
host/runtime, source SHA, exact command, sample counts, and profile write-up.

`python scripts/run_benchmark.py` writes its host- and time-dependent report to
`.artifacts/benchmark/benchmark.md` and its JSON metrics to
`.artifacts/benchmark/current.json`. These runtime outputs have no byte-drift
check and must not replace `docs/perf/load-benchmark-latest.md` or an archived
snapshot. They also must not replace `docs/benchmark-baseline.json`, which is a
reviewed gate-policy input rather than generated runtime output. CI compares
the fresh JSON metrics with that tracked gate baseline; promote evidence only
under a date-stamped name with its run provenance.

`python tests/load/run_load_test.py` writes the Locust p99 CI-smoke CSV prefix
to `.artifacts/load/results` and JSON metrics to `.artifacts/load/results.json`.
Relative outputs resolve from the project root, and the runner refuses
destinations under `docs/perf/` or `tests/load/` before seed or Locust work.
`make load-test` invokes this runner with the localhost default and the
50 users / 10 spawn-rate / 60-second profile. Compare a run with
`python scripts/check_performance.py --baseline docs/benchmark-baseline.json
--current .artifacts/load/results.json`. This is host- and time-dependent
CI-smoke runtime evidence, not a byte-regenerated tracked reference, production
SLA, full-load benchmark, or acceptance. Promote a reviewed result only under
a new date-stamped identity with provenance.

To compare repeated local runs, append one results file with
`python scripts/record_perf_history.py --results .artifacts/benchmark/current.json`,
then run `python scripts/plot_perf_history.py`. The commands own
`.artifacts/perf-history/history.json`, `history.html`, and optional
`history.png`; they refuse to overwrite the retired tracked history or write
plots under `docs/`. CI does not persist this history across runners, so do not
cite the local trend as continuous CI or release evidence.

`python scripts/benchmark_freshness.py` writes the in-process demo report to
`.artifacts/freshness/freshness-benchmark.md` and machine-readable results to
`.artifacts/freshness/current.json`. Do not overwrite the tracked
`docs/perf/freshness-benchmark.md` lifecycle page or its archived snapshot.
Promote a meaningful run only under a date-stamped name with its JSON companion
and exact run, host, and source provenance.

`python scripts/benchmark_freshness_realpath.py` writes the Kafka → Flink
streaming-hop result to `.artifacts/freshness/realpath-current.json`. Run its
Kafka/Flink prerequisites on `deproject-mac`, not the Windows host. The driver
refuses to overwrite the immutable
`docs/perf/freshness-realpath-2026-06-30.md` record; promote a reviewed run only
under a new date-stamped evidence identity with exact source, host, runtime,
command, configuration, sample count, miss count, and JSON hash.

`python scripts/benchmark_freshness_e2e.py` writes the S8 real-path report to
`.artifacts/freshness/e2e-realpath.md` and machine-readable results to
`.artifacts/freshness/e2e-realpath-current.json`. Run its Kafka/Flink/bridge/
ClickHouse/Redis/API prerequisites on `deproject-mac`, not the Windows host.
Do not overwrite the tracked `docs/perf/freshness-e2e-realpath.md` lifecycle
page or its archived 2026-07-09 snapshot; promote only date-stamped evidence
with exact run, host, source, configuration, and JSON-companion provenance.

`python scripts/benchmark_throughput_realpath.py` writes the real-path report
to `.artifacts/throughput/realpath-current.md` and machine-readable results to
`.artifacts/throughput/realpath-current.json`. Run its Kafka/Flink/bridge/
ClickHouse prerequisites on `deproject-mac`, not the Windows development host.
Do not overwrite the tracked `docs/perf/throughput-realpath.md` lifecycle page
or its archived S10 baseline; promote only date-stamped evidence with exact
run, host, source, and configuration provenance.

`python scripts/benchmark_scale_own_data.py` writes the S13 own-data scale
reports to `.artifacts/scale/own-data-current.md` and
`.artifacts/scale/own-data-current.json`. Run its live ClickHouse workload on
`deproject-mac`, not the Windows host. The driver refuses to overwrite
`docs/perf/scale-own-data-2026-07-11.md`; promote a reviewed run only under a
new date-stamped identity with exact source, host/runtime, command,
configuration, volume/check results, and Markdown/JSON hashes.

`python scripts/perf/auth_bench.py` writes its host-dependent legacy-path
microbenchmark to `.artifacts/perf/auth-bench-current.md`. Run the full bcrypt
workload on `deproject-mac`, not the Windows development host. The driver uses
explicit legacy bcrypt semantics and refuses to overwrite
`docs/perf/auth-bench.md` or the immutable 2026-05-26 record. Promote a reviewed
run only under a new date-stamped identity with exact source, host/power,
Python/dependency, command/configuration, sample-count, boundary, and report-hash
provenance.

`python -m scripts.run_nl_sql_eval` writes the direct-translator result to
`.artifacts/nl-sql-eval/current.md`. Relative outputs resolve from the project
root, and the command rejects every path under `docs/perf/` before running the
evaluation. In particular, it cannot overwrite
`docs/perf/nl-sql-eval-2026-07-01.md` or
`docs/perf/nl-sql-eval-sonnet5-2026-07-01.md`. The rule-based path uses the
fixed in-memory DuckDB demo set; the opt-in LLM path is live and
non-deterministic. Neither is the served `/query` path, a production benchmark,
an SLA, or acceptance. Promote a reviewed result only under a new date-stamped
identity with source, host/runtime, engine/model, exact command/configuration,
and report-hash provenance.

## Dependabot pip PRs and `uv.lock`

Dependabot bumps grouped pip dependencies in `pyproject.toml` **without**
regenerating `uv.lock`, so the `lock-check` gate (`uv lock --check`) fails on
every such PR. Bring the lockfile along by hand:

```bash
gh pr checkout <pr-number>
uv lock
git add uv.lock && git commit -m "chore(deps): regenerate uv.lock for the group bump"
git push
gh pr update-branch <pr-number>   # branch protection requires up-to-date branches
```

Then let CI finish and merge as usual. GitHub Actions and npm bumps do not
need this — only the pip ecosystem is locked with uv.

## Architecture decisions

Significant design changes should include an ADR in `docs/decisions/`.

Start with:

- [docs/architecture.md](docs/architecture.md)
- [docs/release-readiness.md](docs/release-readiness.md)
- existing ADRs under `docs/decisions/`

## Documentation expectations

If you change the HTTP surface or operational behavior, update the matching docs:

- `docs/api-reference.md`
- `docs/architecture.md`
- `docs/runbook.md`
- `docs/security-audit.md` when the control surface changes

## Commit conventions

Use conventional commit prefixes:

- `feat:`
- `fix:`
- `docs:`
- `chore:`
- `refactor:`
- `test:`
