# v1.1.0 Release — PUBLISHED

**Status (verified 2026-05-23 via live registry queries):** v1.1.0 is
published on all three registries. The "3 web-UI MFA steps" item in
earlier memory was stale — the work was completed at the original
publish time (late April / early May 2026).

## Live registry state

| Registry | Package | Version | Upload time (UTC) | Owner / maintainer |
|----------|---------|---------|-------------------|--------------------|
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.1.0/) | 1.1.0 | 2026-04-29 09:07 | `brownjuly` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.1.0/)   | 1.1.0 | 2026-04-29 09:07 | `brownjuly` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.1.0) | 1.1.0 | 2026-05-01 03:42 | `yuliaedomskikh` |

## Re-verify

```bash
# PyPI metadata
curl -sf "https://pypi.org/pypi/agentflow-runtime/1.1.0/json" -o /dev/null && echo OK
curl -sf "https://pypi.org/pypi/agentflow-client/1.1.0/json"  -o /dev/null && echo OK

# PyPI install smoke
python -m venv /tmp/.afcheck && . /tmp/.afcheck/bin/activate
pip install agentflow-runtime==1.1.0 agentflow-client==1.1.0
python -c "from importlib.metadata import version; print(version('agentflow-runtime'), version('agentflow-client'))"

# npm metadata
npm view "@yuliaedomskikh/agentflow-client@1.1.0" version dist.tarball
```

PyPI page artifacts (already on production CDN):

```
agentflow_runtime-1.1.0-py3-none-any.whl   153 644 bytes
agentflow_runtime-1.1.0.tar.gz             122 675 bytes
agentflow_client-1.1.0-py3-none-any.whl     27 791 bytes
agentflow_client-1.1.0.tar.gz               19 194 bytes
```

npm artifact:

```
@yuliaedomskikh/agentflow-client@1.1.0
shasum 9970911b9ca05eb6cff070523e596af21181840f
fileCount 16, ~33 KB unpacked
```

## What was actually required (so the next release can skip this dance)

PyPI Trusted Publishers configured on the project pages
(`/manage/project/agentflow-runtime/settings/publishing/` and
the same for `agentflow-client`). The OIDC flow used by
`pypa/gh-action-pypi-publish@release/v1` in
[`.github/workflows/publish-pypi.yml`](../../.github/workflows/publish-pypi.yml)
hits those configurations — no API token, no per-publish MFA. The
2026-04-29 publish run is the proof those settings exist and accept
the workflow's identity.

NPM_TOKEN was added to the repo secrets at GitHub
(`/settings/secrets/actions`). It is consumed by
[`.github/workflows/publish-npm.yml`](../../.github/workflows/publish-npm.yml).
The 2026-05-01 publish run is the proof that secret exists and has
publish scope for the `@yuliaedomskikh` org.

## Tag state

Tag `v1.1.0` points at commit `2c72387` (the commit that triggered
the publish run). Current `main` is many commits ahead — DV2.0 demo
work, multi-branch fan-out, asciinema cast. None of that has been
re-released; v1.1.0 on the registries represents the pre-DV2 state.

If the dv2-multi-branch work needs to be released as part of a new
version, cut **v1.2.0** rather than re-tagging v1.1.0:

```bash
# 1) Bump versions
#    - pyproject.toml: version = "1.2.0"
#    - sdk/pyproject.toml: version = "1.2.0"
#    - sdk/agentflow/__init__.py: __version__ = "1.2.0"
#    - sdk-ts/package.json: "version": "1.2.0"
# 2) Update CHANGELOG.md [Unreleased] -> [1.2.0]
# 3) Tag and push
git tag -a v1.2.0 -m "AgentFlow v1.2.0 — DV2.0 multi-branch demo + fanout CDC"
git push origin v1.2.0
# 4) Watch publish workflows
gh run watch
```

But that's a release decision, not a chore. Default: leave v1.1.0 as
the stable line, treat dv2 work as "shown but not packaged" until
there's a reason to ship it as v1.2.0.
