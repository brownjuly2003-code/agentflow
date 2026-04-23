# Contributing to AgentFlow

## Development setup

Use the Quick start in [README.md](README.md) and choose the setup script that matches your shell:

- PowerShell: `. .\scripts\setup.ps1`
- macOS / Linux: `source ./scripts/setup.sh`

For the fastest local loop, use `make demo`. For a production-shaped stack with observability, use `docker compose -f docker-compose.prod.yml up -d`.

## Running tests

Release verification slice:

```bash
python -m pytest tests/unit tests/integration tests/sdk -v
```

Additional suites when your change touches those areas:

```bash
python -m pip install -e ".[cloud,contract]"
python -m pytest tests/contract tests/property tests/chaos tests/e2e -v
cd sdk-ts && npm test
```

## Before submitting a PR

1. Tests pass:

```bash
pytest tests/
```

2. Security diff is clean:

```bash
bandit -r src sdk --ini .bandit --severity-level medium -f json -o .tmp/bandit-current.json
python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
```

3. Benchmark does not regress past the release gate:

```bash
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current .artifacts/load/results.json --max-regress 20
```

4. Contracts are still in sync:

```bash
python scripts/generate_contracts.py --check
```

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
