# Dependency/Supply Chain Audit - 2026-04-27

Scope: `D:\DE_project`, dependency and release supply chain only.

Baseline:
- HEAD: `4a13d36`
- Tracked files: `597`
- Visible files excluding `.git/.pytest_cache`: `606`
- Bundle/key count: n/a for this audit
- Existing dirty files before this report: `.github/workflows/publish-pypi.yml`, `docs/release-readiness.md`, previous audit markdown files. This report only writes `audit_codex_27_04_26_p9.md`.

## Executive Verdict

Release should be blocked until the root source distribution is cleaned and dependency gates are made reproducible.

Hard blockers:
1. Root sdist `dist/agentflow_runtime-1.1.0.tar.gz` includes `config/webhooks.yaml` with an active plaintext webhook secret and also includes `docker/kafka-connect/secrets/*.properties`.
2. Python and npm release inputs are not locked. Repo `npm audit` fails with `ENOLOCK`, and `publish-npm.yml` uses `npm install` instead of `npm ci`.
3. Current Python environment has known vulnerabilities in release-relevant packages, including `dagster==1.12.22` and the LangChain integration stack.
4. Security CI does not audit npm dependencies, does not cover `integrations/pyproject.toml`, and uses `aquasecurity/trivy-action@master`.

## Dependency Inventory

Python package surfaces:
- `pyproject.toml`
- `sdk/pyproject.toml`
- `integrations/pyproject.toml`
- `requirements.txt`

npm package surface:
- `sdk-ts/package.json`

Lockfiles found:
- Python: none (`poetry.lock`, `Pipfile.lock`, `uv.lock`, `pdm.lock`, constraints lock not found)
- npm: none (`package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock` not found)
- Only `sdk-ts/node_modules/.package-lock.json` exists locally under ignored `node_modules`, which is not a repo lockfile.

Version pinning:
- Most Python deps use broad ranges, for example `dagster>=1.7,<2`, `langchain>=0.3,<1`, `pytest>=8.3,<9`.
- Exact pins exist for `apache-flink==1.19.1` and `schemathesis==4.10.2`.
- Build backend requires are unpinned: `requires = ["hatchling"]`.
- npm dev deps use caret ranges: `typescript: ^5.9.3`, `vitest: ^3.2.4`.

## Vulnerabilities

`uvx pip-audit --path .\.venv\Lib\site-packages -s osv` found 8 known vulnerabilities in 7 packages:

| Package | Version | Advisory | Fixed version | Release relevance |
|---|---:|---|---:|---|
| `dagster` | `1.12.22` | `GHSA-mjw2-v2hm-wj34` SQL injection via dynamic partition keys | `1.13.1` | Runtime dependency, release blocker |
| `langchain-core` | `0.3.84` | `CVE-2026-26013` SSRF via `image_url` token counting | `1.2.11` | Integration stack blocker |
| `langchain-core` | `0.3.84` | `CVE-2026-34070` path traversal in legacy `load_prompt` functions | `1.2.22` | Integration stack blocker |
| `langchain-text-splitters` | `0.3.11` | `GHSA-fv5p-p927-qmxr` SSRF redirect bypass | `1.1.2` | Transitive integration blocker |
| `langsmith` | `0.7.30` | `GHSA-rr7j-v2q5-chgv` streaming token events bypass redaction | `0.7.31` | Transitive integration blocker |
| `mako` | `1.3.10` | `GHSA-v92g-xgxw-vvmm` path traversal in `TemplateLookup` | `1.3.11` | Transitive via Dagster/Alembic |
| `pip` | `26.0.1` | `CVE-2026-3219` archive interpretation conflict | none listed | Tooling, not app runtime |
| `pytest` | `8.4.2` | `CVE-2025-71176` tmpdir handling | `9.0.3` | Dev/CI, not runtime |

`safety check --json` against the current venv found 4 entries in 260 packages:
- `pytest==8.4.2` / `CVE-2025-71176`
- `langchain-core==0.3.84` / `CVE-2026-26013`
- `langchain-core==0.3.84` / `CVE-2026-34070`
- `langchain==0.3.28` / Safety advisory `88512`

Verification notes:
- `dagster` is a direct runtime dependency and is imported in `src/orchestration/dags/daily_batch.py`.
- Searches did not find direct project calls to `load_prompt`, `load_prompt_from_config`, `get_num_tokens_from_messages`, `HTMLHeaderTextSplitter`, `split_text_from_url`, or `TemplateLookup`.
- LangChain is still a direct integration dependency in `integrations/pyproject.toml` and root optional dependency `integrations`; treat the integration package/extra as blocked until upgraded or explicitly excluded from release.
- `pip check` passed: no broken installed requirements.

## Bandit Baseline

Configured baseline:
- `.bandit-baseline.json`
- Generated: `2026-04-17T09:52:26Z`
- Findings: 1

Baselined finding:

| Test | File | Line | Text | Release blocker |
|---|---|---:|---|---|
| `B310` | `src\serving\backends\clickhouse_backend.py` | 49 | `urlopen` scheme audit | No |

Current CI-equivalent command:

```text
python -m bandit -r src sdk --ini .bandit --severity-level medium -f json
python scripts/bandit_diff.py .bandit-baseline.json <current-json>
```

Result:

```text
No new findings (baseline: 1 issues)
count=1
B310|MEDIUM|HIGH|src\serving\backends\clickhouse_backend.py:49
```

The `B310` item is self-verified as baselined and not a release blocker: the URL scheme is fixed from `secure` to `http`/`https`, with host/port/database coming from backend config. It should remain tracked and revisited before promoting ClickHouse config to untrusted tenant input.

Full low-severity scan also reports:
- `B105` at `src\quality\monitors\metrics_collector.py:309`: possible hardcoded password `'None'`. This is a false positive / non-blocker.

## Lockfile and Audit Gate Findings

### Finding 1 - Missing npm lockfile blocks npm audit

Severity: High  
Confidence: 10/10  
Status: Verified  
Release blocker: Yes

Evidence:
- `sdk-ts/package.json` exists.
- No `sdk-ts/package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, or `yarn.lock`.
- `npm audit --json` in `sdk-ts` fails:

```text
ENOLOCK: This command requires an existing lockfile.
```

Impact:
- The repository cannot run a real npm audit from committed state.
- `publish-npm.yml` uses `npm install`, so the release build can resolve a different transitive tree per run.

Required release gate:
- Commit a lockfile for the TS SDK.
- Change release/CI install to `npm ci`.
- Make `npm audit --audit-level=high` or equivalent run from the committed lockfile.

Temporary evidence:
- A temp lockfile generated outside the repo from the current `package.json` audited clean: `0` npm vulnerabilities.
- That does not remove the blocker because the result is not reproducible from committed files.

### Finding 2 - Python release/test environments are not locked

Severity: High  
Confidence: 9/10  
Status: Verified  
Release blocker: Yes for app/container/CI release gates

Evidence:
- No Python lock/constraints file.
- Current venv has 259 frozen packages.
- Package metadata uses broad ranges such as `dagster>=1.7,<2`, `langchain>=0.3,<1`, `pytest>=8.3,<9`.

Impact:
- Security audit results are time-dependent.
- A clean install can silently move to different vulnerable or breaking transitive versions.
- Current environment already contains vulnerable versions that the package ranges would not prevent.

Required release gate:
- Add a resolved constraints/lock artifact for CI and release builds.
- For libraries, keep compatible metadata ranges if needed, but test and publish from a locked resolver output.
- Raise minimum versions for known vulnerable packages, for example `dagster>=1.13.1` and fixed LangChain stack versions if the integration extra remains published.

### Finding 3 - Security CI coverage gap

Severity: High  
Confidence: 9/10  
Status: Verified  
Release blocker: Yes

Evidence:
- `.github/workflows/security.yml` Safety job resolves root runtime + `sdk/pyproject.toml` only.
- `integrations/pyproject.toml` is not included in the Safety inputs.
- npm dependencies are not audited in security CI.
- Trivy action is unpinned floating ref: `aquasecurity/trivy-action@master`.

Impact:
- The vulnerable LangChain integration stack can pass the security workflow.
- npm package publication can pass without an npm vulnerability gate.
- Floating action ref allows upstream action changes to alter the security scanner behavior without a reviewed repo change.

Required release gate:
- Add `integrations/pyproject.toml` and optional extras to dependency audit scope, or explicitly document that integrations are not shipped.
- Add npm lockfile audit to security CI.
- Pin third-party actions to immutable SHAs or at least a stable release tag, not `master`.

## Release Artifact Findings

### Finding 4 - Root sdist publishes active plaintext secret

Severity: Critical  
Confidence: 10/10  
Status: Verified  
Release blocker: Yes

Evidence:
- `config/webhooks.yaml` is tracked.
- It contains:

```text
secret: HsMZKL2-gtXmH_SvBuwibKemoLNqKEVMnG4RECGgKLk
active: true
```

- The same file is inside `dist/agentflow_runtime-1.1.0.tar.gz`.
- Root sdist also includes `docker/kafka-connect/secrets/mysql.properties` and `postgres.properties`, both with `password=agentflow`.

Exploit scenario:
1. Attacker downloads the published source distribution.
2. Attacker extracts `config/webhooks.yaml`.
3. If any deployment reused the default tracked webhook config, the attacker has the HMAC/signing secret for that callback registration.
4. Attacker can forge webhook-related traffic or bypass integrity assumptions for that default registration.

Required release gate:
- Rotate the exposed webhook secret.
- Remove generated runtime state from tracked config.
- Exclude `config/webhooks.yaml` and `docker/kafka-connect/secrets/*` from sdists.
- Replace with `.example` files or generated-on-first-run defaults.
- Add a release check that fails if sdists contain files matching `*secret*`, `webhooks.yaml`, `.env`, `api_keys.yaml`, or `docker/**/secrets/**` unless explicitly allowlisted.

### Finding 5 - Root sdist is too broad

Severity: High  
Confidence: 9/10  
Status: Verified  
Release blocker: Yes

Evidence:
- `dist/agentflow_runtime-1.1.0.tar.gz` contains 598 entries, including `.github/workflows`, `config/`, `docker/`, docs, tests, notebooks, examples, `sdk/`, `sdk-ts/`, and `integrations/`.
- Wheel is narrower: `dist/agentflow_runtime-1.1.0-py3-none-any.whl` contains 100 entries and does not include `config/webhooks.yaml`.

Impact:
- The sdist exposes operational files and local runtime state that are not required for installing the runtime package.
- The artifact makes accidental secret publication more likely.

Required release gate:
- Add explicit Hatch sdist include/exclude config.
- Keep root sdist to package source, package metadata, README/LICENSE/CHANGELOG, and required non-secret package data only.
- Rebuild and re-run `twine check`, artifact content listing, and secret scan.

### Release artifact checks that passed

`uvx twine check dist\* sdk\dist\*`:
- `dist/agentflow_runtime-1.1.0-py3-none-any.whl`: passed with warnings
- `dist/agentflow_runtime-1.1.0.tar.gz`: passed with warnings
- `sdk/dist/agentflow_client-1.1.0-py3-none-any.whl`: passed
- `sdk/dist/agentflow_client-1.1.0.tar.gz`: passed

Warnings on root runtime artifacts:
- `long_description_content_type` missing
- `long_description` missing

npm dry-run pack:
- `npm pack --dry-run --json`
- Package: `@agentflow/client@1.1.0`
- Entries: 16
- Bundled deps: none
- Includes `dist/`, `README.md`, `package.json`

Artifact hashes:

| Artifact | SHA256 |
|---|---|
| `dist/agentflow_runtime-1.1.0-py3-none-any.whl` | `D603769A1A4AAD19E989EAA353951F3046ACE4C299314E67121E71227DCFD57B` |
| `dist/agentflow_runtime-1.1.0.tar.gz` | `854FBF3D16ABB5CEAC5473AD5AE829B35CBADEB13A242630A6824A0D2ED30F23` |
| `sdk/dist/agentflow_client-1.1.0-py3-none-any.whl` | `A934DB0E9A98168DBC5B3F3C44FC9142B0FDBDFB8CE285380BFC5D94F91A0848` |
| `sdk/dist/agentflow_client-1.1.0.tar.gz` | `FC9C344D3AA2FCAE1BC7299CF95D4F17F9D87CCBD2974AD882FD82C1F786AE3D` |

## What Should Become Release Blockers

Block every production release on:
1. No plaintext secrets in repo release artifacts, including sdists.
2. `npm audit` must run from a committed lockfile and pass the configured severity threshold.
3. Python dependency audit must run from locked/resolved release inputs and include root, SDK, integrations, and published extras.
4. No High/Critical vulnerabilities in runtime, published extras, or release tooling unless a documented exception includes exploitability analysis and expiry.
5. Bandit diff must show no new medium/high findings relative to baseline.
6. Third-party GitHub Actions in release/security workflows must not use floating branch refs such as `master`.
7. Publish workflows must use reproducible installs: `npm ci` for npm and locked/constraints-driven Python installs for build and checks.
8. Built artifacts must pass `twine check`/`npm pack --dry-run` and an artifact content allowlist/secret scan.

Not release blockers for this run:
- Current baselined Bandit `B310`, because it is already baselined and no new medium/high Bandit findings appeared.
- Bandit low `B105` on literal `None`, because it is a false positive.
- `pytest` CVE for production runtime release, because it is dev/CI scope. It should still block CI base-image refresh if untrusted local users share the runner.
- `pip` advisory without a listed fixed version, unless the release process downloads untrusted mixed-format archives with this pip version.

## Recommended Remediation Order

1. Stop publishing the current root sdist. Rotate `config/webhooks.yaml` secret and remove generated webhook registrations from tracked/released files.
2. Add sdist include/exclude rules and rebuild artifacts. Verify root sdist no longer includes `config/webhooks.yaml`, `docker/**/secrets/**`, `.github/`, local docs archives, notebooks, or runtime state.
3. Add npm lockfile and switch publish workflow to `npm ci`; add `npm audit`.
4. Add Python constraints/lock output for release/security CI. Raise minimum versions for fixed vulnerable packages.
5. Extend security CI to cover `integrations/pyproject.toml` and npm.
6. Pin `aquasecurity/trivy-action` away from `master`.
7. Re-run: `pip-audit`, `safety`, `npm audit`, Bandit diff, Trivy, `twine check`, `npm pack --dry-run`, and artifact secret scan.

## Tooling Notes

Commands run included:
- `pip check`: passed.
- `pip freeze`: 259 installed packages.
- `uvx pip-audit --path .\.venv\Lib\site-packages -f json --timeout 60 -s osv`: found 8 vulnerabilities.
- `python -m safety check --json`: found 4 vulnerabilities; command is deprecated but still useful as a second signal.
- `npm audit --json` in `sdk-ts`: failed with `ENOLOCK`.
- Temp npm lock audit outside repo: 0 vulnerabilities.
- `python -m bandit -r src sdk --ini .bandit --severity-level medium -f json` + `scripts/bandit_diff.py`: no new findings.
- `uvx twine check dist\* sdk\dist\*`: passed, with root metadata warnings.
- `npm pack --dry-run --json`: passed.

Disclaimer: this is an AI-assisted security review, not a substitute for a professional security audit or penetration test.
