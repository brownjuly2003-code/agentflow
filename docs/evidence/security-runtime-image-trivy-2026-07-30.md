# Runtime image Trivy remediation — 2026-07-30

## Scope

This record covers the API runtime image only. It does not claim a signed
registry release, an external penetration test, or production acceptance.

## Trigger

GitHub Actions Security Scan run
[`30570556301`](https://github.com/brownjuly2003-code/agentflow/actions/runs/30570556301)
scanned commit `72b960930302ecbced46c89479a5b09082f0a406` with Trivy `0.70.0`.
The image job reported:

- `GHSA-6v7p-g79w-8964`: vendored `msgpack 1.1.2`;
- `CVE-2025-47273`: stale `setuptools 70.3.0`.

The uploaded CycloneDX SBOM associated both findings with the final installer
layer and no application package path. The same layer listed other packages
vendored by `pip`, while the actual installed setuptools distribution was the
already-fixed `82.0.1`. Neither vulnerable version came from
`requirements-docker.lock`.

## Remediation

`Dockerfile.api` still performs the hash-locked dependency install, installs
the AgentFlow wheel with `--no-deps`, and runs `pip check`. It then removes
runtime-only installer tooling:

```dockerfile
python -m pip uninstall --yes pip setuptools wheel
```

The builder stage is unchanged. A unit contract requires the uninstall to
remain in the final stage and after `pip check`.

## Independent Mac validation

Validation used an isolated clone at
`/tmp/agentflow-security-72b9609-codex-01`, based on exact commit
`72b960930302ecbced46c89479a5b09082f0a406`, plus the candidate
image-affecting files:

- `Dockerfile.api` blob `9cc33d81a88802991f632225a45f9422ab8e4358`;
- `src/quality/monitors/metrics_collector.py` blob
  `475c656b0c7de9418e2447bd6b5cca36b9026146` — the path as it existed at
  `72b9609`; the module moved to
  `src/agentflow_runtime/quality/monitors/metrics_collector.py` in the P2-6
  namespace migration (`1096e2e`, 2026-08-23), after this record was taken.

The image was built from the pinned `python:3.11-slim` digest already declared
in `Dockerfile.api`:

```text
agentflow-api:security-codex-72b9609
manifest list sha256:934357fe14e8f6ed3a712eb7ae8bec1a369aad06f54691eadd2b8aa7e2cd1591
```

Build output confirmed that `pip 26.2`, `setuptools 82.0.1`, and `wheel 0.47.0`
were uninstalled only after `pip check` returned
`No broken requirements found`.

Runtime checks:

- `python -m pip --version` failed with `No module named pip` as intended;
- `from src.serving.api.main import app` succeeded (`AgentFlow Query API`);
- Trivy `0.70.0`, with `HIGH,CRITICAL`, `--ignore-unfixed`, and
  `--exit-code 1`, exited `0`;
- Trivy summary: Debian `13.5` vulnerabilities `0`; every detected Python
  package vulnerabilities `0`.

## Dependency-lock revalidation

Final CI dependency diagnosis added `pyiceberg-core==0.7.0` to the cloud
profile and hash lock. Codex rebuilt the image from isolated Mac clone
`/tmp/agentflow-ci-f11-codex-deps-01`, based on exact `f11fd59` plus the five
candidate dependency files:

```text
agentflow-api:security-codex-f11deps-01
manifest list sha256:95254620bf98e73ce89feae28e0b178a3cf00956c7e63eedd40f8958705645d1
```

The rebuilt Python 3.11 image installed core 0.7.0 through
`requirements-docker.lock`, passed `pip check`, removed installer tooling,
and preserved the API import. A fresh official Trivy `0.70.0` container scan
with the same HIGH/CRITICAL failure policy exited `0`; every reported OS and
Python package row was clean. Dependency root-cause and Python 3.13/MCP
verification are in
[dependency-compatibility-2026-07-30.md](dependency-compatibility-2026-07-30.md).

## Evidence boundary

This is content-level local acceptance of the candidate runtime image. The
next pushed SHA must still pass the repository's GitHub Security Scan and all
other required checks. Published-image signing and external penetration-test
evidence remain separate gates.
