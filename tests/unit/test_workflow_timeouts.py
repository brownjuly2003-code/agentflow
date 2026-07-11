"""Policy: every workflow job declares a bounded timeout-minutes.

The 2026-07-11 audit (P1-5) found 21 of 35 workflow jobs with no
`timeout-minutes` at all, including the core `test-unit`, `test-integration`,
`bandit`, `safety`, and the publish jobs — a hung step blocks the runner (and,
for required checks, every PR behind it) until GitHub's 360-minute default
kicks in instead of failing fast. This is a ratchet test, same pattern as
test_workflow_action_pinning.py and test_flink_smoke_workflow.py's own
per-job timeout check: every job in every workflow must set a positive
`timeout-minutes`.

`backup.yml` is intentionally excluded — it is owned by a separate DR
workstream (audit P1-2) editing concurrently with this change.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"

EXCLUDED_WORKFLOWS = {"backup.yml"}


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS_DIR.glob("*.yml") if p.name not in EXCLUDED_WORKFLOWS)


def _jobs(path: Path) -> dict:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return workflow.get("jobs", {}) or {}


def test_workflow_files_exist() -> None:
    # Guard the policy test itself: if globbing breaks, fail loudly instead
    # of green-on-empty.
    assert _workflow_files(), "no workflow files found under .github/workflows"


def test_every_job_has_a_positive_bounded_timeout() -> None:
    offenders = []
    for path in _workflow_files():
        for job_id, job in _jobs(path).items():
            if not isinstance(job, dict):
                continue
            timeout = job.get("timeout-minutes")
            if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
                offenders.append(f"{path.name}:{job_id} timeout-minutes={timeout!r}")
    assert not offenders, "jobs without a positive timeout-minutes:\n" + "\n".join(offenders)


def test_no_job_declares_an_unreasonably_long_timeout() -> None:
    # A ceiling, not a target: this catches a copy-pasted 360 (GitHub's own
    # default) or similar "timeout-minutes in name only" values slipping in
    # instead of an actual bound. Generous enough for the heaviest existing
    # lane (mutation.yml at 60) plus headroom.
    offenders = []
    for path in _workflow_files():
        for job_id, job in _jobs(path).items():
            if not isinstance(job, dict):
                continue
            timeout = job.get("timeout-minutes")
            if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 90:
                offenders.append(f"{path.name}:{job_id} timeout-minutes={timeout}")
    assert not offenders, "jobs with a suspiciously long timeout-minutes:\n" + "\n".join(offenders)
