# Lessons learned — CI repair + Q2 architecture sprints (2026-04)

Patterns surfaced across the three back-to-back sprints
(`docs/codex-tasks/2026-04-22/`, `2026-04-23/`, and Q2 architecture
`2026-04-Q2-architecture/`) plus the audit follow-up wave in late April.
Recorded here so the next CI / release / packaging change does not have
to relearn them.

---

## 1. A06 dependency-profile enforcement

**Lesson.** Listing `pip install -e .[extras]` in workflow YAML by hand
guarantees drift between what CI installs and what tests actually need.
`tests/unit/test_contract_dependencies.py` now compares
`[tool.agentflow.dependency-profiles.targets]` against every
`pip install` line in `.github/workflows/*.yml` and fails the build on
divergence.

**Apply.** Never edit a workflow's install line directly. Add or
rename a profile in `pyproject.toml`, then let the contract test prove
all workflows match. The same test catches a forgotten `sdk/` or
`integrations/` editable install too.

**Concrete trace.** `87e5f8e` (A01+A06 combined PR) → `6b60674` was a
manual workflow patch that immediately drifted → `97a1902` (A06 path)
fixed it the right way and stayed green.

---

## 2. Single-run CI baseline is an anti-pattern

**Lesson.** Locust on a 4-core GitHub Actions runner produces wildly
different p99 across runs (3× swings). One run is not a baseline; it is
a sample. The first version of A03 / T27 split-decision gating used a
single `load-test.yml` run and produced a chronic red that lasted
weeks.

**Apply.** When introducing or revising a perf gate, capture at least
three back-to-back runs of the same workflow on a stable HEAD,
median-aggregate, then commit `docs/benchmark-baseline.json` with the
specific `run_id` set in the metadata. The current baseline records
two run IDs (`24920594700` + `24979982182`) precisely to avoid the
one-sample mistake.

**Concrete trace.** `cd4a11a` (T27 thresholds rework, p99-keyed +
CI-runner baseline + archive of local-only baseline) flipped chronic
red to green. Latest 10 runs on `main` (post-DV2 merge) all success.

---

## 3. FastAPI / dependency version drift detection

**Lesson.** A contract test asserting an exact ValidationError schema
shape will break the day CI bumps FastAPI minor and the field order or
nesting changes. We hit `local fastapi 0.128.0` vs
`CI fastapi 0.136.1` — both legitimate, both produced different
`detail` envelopes for the same input.

**Apply.** Normalize before asserting on framework-owned response
shapes. `tests/contract/` uses a `_normalize_validation_error()` helper
that strips fields unrelated to the contract under test (`loc`, `ctx`,
`url`). Diagnostic artifacts live in
`docs/perf/test_openapi_compliance-divergence-2026-04-25.md`.

**Concrete trace.** `d700a26` (T29 fix(contract)).

---

## 4. PyPI namespace pre-claim check before any rename

**Lesson.** A01 spent two sprints planning the SDK rename
`agentflow` → SDK is `agentflow`, runtime is `agentflow-runtime`.
The name `agentflow` had been a stale, abandoned project on pypi.org
since 2023-05-29 (`Stoyan/llmflow@0.0.2`). PEP 541 takeover is
2–6 weeks — outside any reasonable release window.

**Apply.** Before locking a distribution name in any spec:

```bash
for n in <candidate-names>; do
  curl -sf https://pypi.org/pypi/$n/json -o /dev/null \
    && echo "$n: TAKEN" \
    || echo "$n: FREE"
done
```

Run the same sweep against npm:

```bash
for n in <candidate-names>; do
  curl -sf https://registry.npmjs.org/$n -o /dev/null \
    && echo "$n: TAKEN" \
    || echo "$n: FREE"
done
```

Also: when renaming, **grep every `pyproject.toml`** in the tree.
T30 spec missed `integrations/pyproject.toml` and CI failed on the
follow-up commit (`0e6abcd` → `b51fa70`).

**Concrete trace.** T30 emergency rename (`0e6abcd`+`b51fa70`).

---

## 5. Required-status-check self-reference deadlock

**Lesson.** A workflow step that pushes back to `main` (e.g.
`record-deployment` writing `.dora/`, or `load-test.yml` writing
`docs/benchmark-history.json`) cannot also be in `required_status_checks`
on `main` branch protection. It will reject its own push with
`GH006: changes must pass all required checks` because *itself* is
not yet completed.

**Apply.** Auto-commit bots either (a) push to a side branch, or
(b) are excluded from `required_status_checks`. If you add a
"commit benchmark history" step, also remove that workflow from the
protection list — both `gh api` PATCH commands in one batch.

**Concrete trace.** `b2c0bc0` removed `record-deployment` from
`required_status_checks` and dropped the load-test "Commit benchmark
history" step.

---

## 6. Fail-closed auth + a `/v1/health` exception will hide breakage

**Lesson.** After `e8b1237` set `api_keys: []` in
`values-staging.yaml`, the AuthMiddleware fail-closed branch returned
503 on every authenticated route. But `/v1/health` was exempt → green
container probes, green deployment, **red customer paths**. E2E only
caught it because tests carry real API keys.

**Apply.** A health endpoint must touch enough of the auth path to
fail when the rest of the app fails. Either (a) make health
itself require a sentinel key, or (b) add a separate `/v1/readyz`
that does a no-op authenticated call. We chose (b)-equivalent via
restoring three bcrypt-hashed e2e fixture keys to staging.

**Concrete trace.** `b2c0bc0` (Staging Deploy 503 root cause).

---

## 7. DV2 voice-over pipeline (cast → MP4 with synced narration)

**Lesson.** asciinema's `demo.cast` is a perfect base for portfolio
videos but needs voice-over. The reproducible pipeline turned out to
be three off-the-shelf tools, no custom rendering:

1. **edge-tts** (Microsoft Edge TTS, free, no key) generates Russian
   narration from a plain `.txt` script. `ru-RU-SvetlanaNeural` at
   `+25%` rate matches a comfortable 1:30 pitch.
2. **agg** (Rust binary from asciinema/agg releases) renders the cast
   to a GIF — handles ANSI colors, terminal sizing, font choice.
3. **ffmpeg** converts the GIF to MP4, then `setpts` stretches the
   silent video to the narration's duration, then `-map` muxes the
   audio track.

The full script is `docs/dv2-multi-branch/demo_voiced.build.sh`
(commit `175a855`), final artifact `demo_voiced.mp4`
(~92 s, 3.1 MB).

**Apply.** When the deliverable is "a video of the demo", default to
edge-tts + agg + ffmpeg before considering screen recording or
HTML→video tooling. No Docker, no Node/svg-term-cli, no cloud TTS.

**Pitfall.** The repo's top-level `.gitignore` matches `build/`
generically. Put the source artifacts (narration script + build
script) flat next to `demo.cast`, not under a `build/` subdir, or
they get silently ignored. Intermediates (`.demo.gif`,
`.demo_native.mp4`, `.demo_voiced.narration.mp3`) use a leading dot
so they're hidden by convention; no need for a nested `.gitignore`.

---

## How to use this doc

When you hit a CI / release / packaging surprise, search this file
first. If the cause matches an entry, the fix above is already proven
on a real commit. If it doesn't, the next entry to write probably
belongs here — append a section with the same shape (Lesson / Apply /
Concrete trace), bisect to a commit SHA, and link it.
