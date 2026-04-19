from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

HOTFIX_PATTERN = re.compile(r"\b(hotfix|rollback|revert|patch|fix)\b", re.IGNORECASE)
FAILURE_CONCLUSIONS = {"action_required", "failure", "startup_failure", "timed_out"}
SUCCESS_CONCLUSIONS = {"success"}


def _run_git(repo_root: Path, *args: str) -> str:
    git_executable = shutil.which("git") or "git"
    completed = subprocess.run(  # noqa: S603,S607
        [git_executable, *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _format_value(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.2f}{suffix}"


def _fetch_json(url: str, token: str | None) -> dict[str, Any]:
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme for GitHub API: {url}")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentflow-dora-metrics",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)  # noqa: S310
    with urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _parse_repo_slug(repo_root: Path) -> str | None:
    if os.getenv("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]

    try:
        remote_url = _run_git(repo_root, "remote", "get-url", "origin").strip()
    except subprocess.CalledProcessError:
        return None

    match = re.search(r"github\.com[:/](?P<slug>[^/]+/[^/.]+)(?:\.git)?$", remote_url)
    if match is None:
        return None
    return match.group("slug")


def _load_commits(repo_root: Path, branch: str, since: datetime) -> list[dict[str, Any]]:
    output = _run_git(
        repo_root,
        "log",
        branch,
        "--reverse",
        f"--since={since.isoformat()}",
        "--pretty=format:%H%x09%P%x09%aI%x09%cI%x09%s",
    )
    commits: list[dict[str, Any]] = []
    for line in output.splitlines():
        sha, parents_text, authored_at, committed_at, subject = line.split("\t", maxsplit=4)
        commits.append({
            "sha": sha,
            "parents": [parent for parent in parents_text.split() if parent],
            "authored_at": _parse_datetime(authored_at),
            "committed_at": _parse_datetime(committed_at),
            "subject": subject,
        })
    return commits


def _merge_start_time(repo_root: Path, commit: dict[str, Any]) -> datetime:
    parents = commit["parents"]
    if len(parents) < 2:
        return commit["authored_at"]

    output = _run_git(
        repo_root,
        "log",
        "--reverse",
        "--pretty=format:%aI",
        f"{parents[0]}..{parents[1]}",
    )
    dates = [_parse_datetime(line) for line in output.splitlines() if line]
    return dates[0] if dates else commit["authored_at"]


def _load_deployment_log(log_path: Path, branch: str, since: datetime) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        ref = str(payload.get("ref", ""))
        if ref not in {branch, f"refs/heads/{branch}"}:
            continue
        recorded_at = payload.get("recorded_at")
        if recorded_at is None:
            continue
        event_time = _parse_datetime(str(recorded_at))
        if event_time < since:
            continue
        events.append({
            "sha": payload.get("sha"),
            "recorded_at": event_time,
            "status": str(payload.get("status", "unknown")),
            "source": "deployment_log",
            "html_url": payload.get("html_url"),
        })
    return sorted(events, key=lambda item: item["recorded_at"])


def _load_github_runs(
    repo_slug: str | None,
    api_url: str,
    token: str | None,
    branch: str,
    since: datetime,
) -> tuple[list[dict[str, Any]], str | None]:
    if not repo_slug or not token:
        return [], None

    runs: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            query = urlencode({
                "branch": branch,
                "event": "push",
                "per_page": 100,
                "page": page,
            })
            payload = _fetch_json(
                f"{api_url}/repos/{repo_slug}/actions/workflows/ci.yml/runs?{query}",
                token,
            )
            workflow_runs = payload.get("workflow_runs", [])
            if not workflow_runs:
                break

            should_continue = False
            for run in workflow_runs:
                created_at = _parse_datetime(run["created_at"])
                updated_at = _parse_datetime(run["updated_at"])
                if updated_at < since:
                    should_continue = True
                    continue
                runs.append({
                    "sha": run.get("head_sha"),
                    "created_at": created_at,
                    "recorded_at": updated_at,
                    "status": str(run.get("conclusion") or run.get("status") or "unknown"),
                    "source": "github_actions",
                    "html_url": run.get("html_url"),
                })

            if should_continue:
                break
            page += 1
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return [], "GitHub Actions history unavailable; falling back to local git/log data."

    runs.sort(key=lambda item: item["recorded_at"])
    return runs, None


def _deployment_events(
    commits: list[dict[str, Any]],
    github_runs: list[dict[str, Any]],
    deployment_log: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    successful_runs = [run for run in github_runs if run["status"] in SUCCESS_CONCLUSIONS]
    if successful_runs:
        return successful_runs, "github_actions"

    successful_log = [event for event in deployment_log if event["status"] in SUCCESS_CONCLUSIONS]
    if successful_log:
        return successful_log, "deployment_log"

    return [
        {
            "sha": commit["sha"],
            "recorded_at": commit["committed_at"],
            "status": "success",
            "source": "git",
            "html_url": None,
        }
        for commit in commits
    ], "git"


def _calculate_mttr(
    github_runs: list[dict[str, Any]],
    deployment_log: list[dict[str, Any]],
) -> dict[str, Any]:
    if github_runs:
        incident_source = "github_actions"
    elif deployment_log:
        incident_source = "deployment_log"
    else:
        incident_source = "unavailable"
    incidents = github_runs or deployment_log
    failures = [event for event in incidents if event["status"] in FAILURE_CONCLUSIONS]

    recoveries_hours: list[float] = []
    unresolved = 0
    for failure in failures:
        recovery = next(
            (
                event
                for event in incidents
                if event["recorded_at"] > failure["recorded_at"]
                and event["status"] in SUCCESS_CONCLUSIONS
            ),
            None,
        )
        if recovery is None:
            unresolved += 1
            continue
        recoveries_hours.append(
            (recovery["recorded_at"] - failure["recorded_at"]).total_seconds() / 3600,
        )

    note = None
    if incident_source == "unavailable":
        note = "No GitHub Actions or deployment log history available."
    elif not failures:
        note = "No failed mainline CI runs in the selected window."
    elif unresolved:
        note = f"{unresolved} failed run(s) are still unresolved in the selected window."

    return {
        "incidents": len(failures),
        "average_hours": _round_or_none(mean(recoveries_hours) if recoveries_hours else None),
        "unit": "hours",
        "source": incident_source,
        "note": note,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute DORA metrics from local git history and GitHub Actions runs.",
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--output")
    parser.add_argument("--github-api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--repo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days <= 0:
        raise SystemExit("--days must be a positive integer.")

    repo_root = Path(__file__).resolve().parents[1]
    since = datetime.now(tz=UTC) - timedelta(days=args.days)
    commits = _load_commits(repo_root, args.branch, since)
    deployment_log = _load_deployment_log(
        repo_root / ".dora" / "deployments.jsonl",
        args.branch,
        since,
    )
    repo_slug = args.repo or _parse_repo_slug(repo_root)
    github_runs, github_note = _load_github_runs(
        repo_slug,
        args.github_api_url.rstrip("/"),
        os.getenv("GITHUB_TOKEN"),
        args.branch,
        since,
    )
    deployments, deployment_source = _deployment_events(commits, github_runs, deployment_log)
    lead_times_hours = [
        max(
            (commit["committed_at"] - _merge_start_time(repo_root, commit)).total_seconds() / 3600,
            0.0,
        )
        for commit in commits
    ]
    average_lead_time = mean(lead_times_hours) if lead_times_hours else None
    median_lead_time = median(lead_times_hours) if lead_times_hours else None
    hotfix_commits = [commit for commit in commits if HOTFIX_PATTERN.search(commit["subject"])]
    failed_deployments = 0
    for deployment in deployments:
        deployment_time = deployment["recorded_at"]
        window_end = deployment_time + timedelta(hours=24)
        if any(
            deployment_time < commit["committed_at"] <= window_end
            for commit in hotfix_commits
        ):
            failed_deployments += 1

    weeks = args.days / 7
    mttr = _calculate_mttr(github_runs, deployment_log)
    report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "window_days": args.days,
        "branch": args.branch,
        "repository": repo_slug,
        "notes": [note for note in [github_note] if note],
        "sources": {
            "git": True,
            "github_actions": bool(github_runs),
            "deployment_log": bool(deployment_log),
        },
        "metrics": {
            "deployment_frequency": {
                "deployments": len(deployments),
                "per_week": _round_or_none(len(deployments) / weeks),
                "unit": "deployments/week",
                "source": deployment_source,
            },
            "lead_time_for_changes": {
                "changes": len(commits),
                "average_hours": _round_or_none(average_lead_time),
                "median_hours": _round_or_none(median_lead_time),
                "unit": "hours",
                "source": "git",
            },
            "change_failure_rate": {
                "failed_deployments": failed_deployments,
                "deployments": len(deployments),
                "percentage": _round_or_none(
                    (failed_deployments / len(deployments) * 100) if deployments else None,
                ),
                "unit": "percent",
                "source": f"{deployment_source}+git_hotfix_heuristic",
            },
            "mttr": mttr,
        },
    }

    print(f"DORA metrics for {args.branch} over the last {args.days} day(s)")
    print(
        "Deployment frequency: "
        f"{report['metrics']['deployment_frequency']['deployments']} deployments total, "
        f"{_format_value(report['metrics']['deployment_frequency']['per_week'])}/week "
        f"[source={deployment_source}]",
    )
    print(
        "Lead time for changes: "
        f"avg {_format_value(report['metrics']['lead_time_for_changes']['average_hours'], 'h')} "
        f"(median "
        f"{_format_value(report['metrics']['lead_time_for_changes']['median_hours'], 'h')}) "
        f"across {len(commits)} change(s)",
    )
    print(
        "Change failure rate: "
        f"{_format_value(report['metrics']['change_failure_rate']['percentage'], '%')} "
        f"({failed_deployments}/{len(deployments)})",
    )
    print(
        "MTTR: "
        f"{_format_value(report['metrics']['mttr']['average_hours'], 'h')} "
        f"across {report['metrics']['mttr']['incidents']} incident(s)",
    )
    if report["metrics"]["mttr"]["note"]:
        print(f"MTTR note: {report['metrics']['mttr']['note']}")
    for note in report["notes"]:
        print(f"Note: {note}")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote report to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
