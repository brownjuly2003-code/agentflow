# Release Rollback / Package Yank

**Last updated:** 2026-05-24

## Symptom

A version already published to PyPI (`agentflow-runtime`, `agentflow-client`)
or npm (`@yuliaedomskikh/agentflow-client`) needs to be pulled because:

- A blocking bug was discovered shortly after release.
- A secret was accidentally bundled into the published artifact.
- A breaking change was shipped under a non-major version bump.
- License or compliance issue (e.g., an LGPL dependency landed in a wheel).

## Severity

Default **Sev 1** if a secret was published — every minute it stays public is
worse. Default **Sev 2** for functional bugs that have a documented workaround.
Default **Sev 3** for cosmetic issues (wrong README, missing CHANGELOG line) —
those should be fixed in the next patch release, not yanked.

## Owner

Release manager (whoever cut the tag). Loop in Security on any secret-leak path
immediately, before doing anything else.

## Detection

1. Verify the bad version is actually live:
   ```
   curl -s https://pypi.org/pypi/agentflow-runtime/<version>/json | jq '.info.version'
   curl -s https://pypi.org/pypi/agentflow-client/<version>/json | jq '.info.version'
   curl -s https://registry.npmjs.org/@yuliaedomskikh/agentflow-client/<version> | jq '.version'
   ```
2. If a secret leak, also verify the artifact contents:
   ```
   pip download agentflow-runtime==<bad-version> --no-deps -d /tmp/yank-evidence/
   unzip -l /tmp/yank-evidence/agentflow_runtime-*.whl
   ```
   Capture the file listing as evidence before yanking — once yanked, it gets
   harder to retrieve.

## Triage

1. **Is it a secret leak?** If yes, escalate to Sev 1 immediately and skip
   straight to mitigation. Every minute of public exposure matters.
2. **Is it the latest version?** If a later version exists that does not have
   the bug, the impact is limited to anyone pinned to the bad version. Yank
   without urgency.
3. **Is there a workaround?** If users can pin to the previous version
   (`pip install 'agentflow-runtime<bad'`), the yank is mostly a hygiene
   action — file the follow-up patch release and yank within the day.
4. **Who installed in the last 24h?** PyPI download stats are eventual but
   approximate impact:
   ```
   curl -s https://pypistats.org/api/packages/agentflow-runtime/recent | jq
   ```

## Mitigation

### Secret leak (Sev 1)

1. **Rotate the leaked secret first**, before doing anything else. The leak is
   public; assume it was scraped within seconds.
2. Yank the affected versions:
   ```
   # PyPI — requires logged-in maintainer in the web UI:
   open https://pypi.org/manage/project/agentflow-runtime/release/<bad-version>/
   # Click "Options" → "Yank".
   ```
   ```
   # npm — requires npm auth as a publisher with deprecate permissions:
   npm deprecate @yuliaedomskikh/agentflow-client@<bad-version> \
     "Security advisory: secret leak. Use <good-version> or later."
   ```
   `npm deprecate` is the recommended path — `npm unpublish` of a public
   package is blocked after 72 hours and is hostile to downstream users even
   inside that window.
3. File a GitHub Security Advisory:
   ```
   gh repo view brownjuly2003-code/agentflow --web
   # Settings → Security → Security advisories → New draft
   ```
4. Publish a patch release with the rotated secret excluded from the wheel.

### Functional bug (Sev 2)

1. Yank on PyPI (web UI, link above). Yanked versions remain installable when
   pinned explicitly (`pip install agentflow-runtime==<yanked>`), but are
   skipped by `pip install agentflow-runtime` with no version pin. That is
   the correct behavior for "do not pick this by default".
2. Deprecate on npm with a message pointing at the next good version:
   ```
   npm deprecate @yuliaedomskikh/agentflow-client@<bad-version> \
     "Fixed in <good-version> — upgrade with: npm i @yuliaedomskikh/agentflow-client@<good-version>"
   ```
3. Cut and publish the patch release with the fix.

### Wrong version was tagged but never published

If the tag exists but `publish-pypi.yml` / `publish-npm.yml` failed before
upload, the recovery is simply to delete the tag and re-tag at the right SHA:

```
git push origin :refs/tags/v<bad-version>
git tag -d v<bad-version>
git tag -a v<good-version> -m "AgentFlow v<good-version>"
git push origin v<good-version>
```

Releasing the same version number twice is **not** possible on PyPI even after
yank — the version number is permanently consumed. Always bump to a new patch
version when republishing.

## Resolution

1. The yanked version is marked as such on PyPI / deprecated on npm.
2. The replacement version is published and verified live:
   ```
   curl -s https://pypi.org/pypi/agentflow-runtime/<good-version>/json | jq '.info.version'
   curl -s https://registry.npmjs.org/@yuliaedomskikh/agentflow-client/<good-version> | jq '.version'
   ```
3. `docs/dv2-multi-branch/RELEASE_STATUS.md` is updated with both the yank and
   the replacement, with timestamps.
4. CHANGELOG documents the yank as a `### Yanked` block under the affected
   version heading. Do not delete the original CHANGELOG entry — keeping it
   in place with a yank note is the audit trail.
5. If a secret was rotated, every downstream system that consumed the old
   secret has been re-credentialed.

## Postmortem trigger

- Mandatory for every Sev 1 secret-leak yank, no exceptions.
- Mandatory for any yank that affected > 50 downloads (`pypistats` recent).
- Recommended for Sev 2 yanks that could have been caught by the release
  smoke checks in `scripts/check_release_artifacts.py` — the postmortem should
  produce a concrete addition to that script so the same class of bug cannot
  ship next time.

## Related

- `docs/dv2-multi-branch/RELEASE_STATUS.md` — current live versions and
  re-verify recipe.
- `.github/workflows/publish-pypi.yml`, `.github/workflows/publish-npm.yml` —
  the workflows you may need to fix before republishing.
- `scripts/release.py` — local helper for bumping versions and tagging.
- `docs/lessons/ci-repair-sprint-2026-04.md` § "PyPI namespace pre-claim" —
  why the SDK is called `agentflow-client`, not `agentflow`.
