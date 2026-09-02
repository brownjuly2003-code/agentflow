"""Enforce tracked Markdown allowlists under ``docs/`` and the repository root."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

CURATED_WALKTHROUGH_ROOT = frozenset(
    {
        "docs/components.md",
        "docs/concepts.md",
        "docs/deployment.md",
        "docs/index.md",
        "docs/observability.md",
        "docs/quickstart.md",
        "docs/sdk.md",
        "docs/troubleshooting.md",
    }
)

CURRENT_REFERENCE_ROOT = frozenset(
    {
        "docs/PROJECT_CLOSURE.md",
        "docs/README.md",
        "docs/STATUS.md",
        "docs/api-reference.md",
        "docs/architecture.md",
        "docs/clickhouse-migration.md",
        "docs/contributing.md",
        "docs/engineering-standards.md",
        "docs/glossary.md",
        "docs/integrations.md",
        "docs/release-readiness.md",
        "docs/runbook.md",
        "docs/security-audit.md",
    }
)

PRODUCT_AND_DOMAIN_SPEC_ROOT = frozenset(
    {
        "docs/domain.md",
        "docs/generator-spec.md",
        "docs/ops-surfaces-spec.md",
        "docs/product.md",
    }
)

GENERATED_REFERENCE_ROOT = frozenset(
    {
        "docs/quality.md",
        "docs/sdk-capabilities.md",
    }
)

ROOT_MARKDOWN_ALLOWLIST = frozenset().union(
    CURATED_WALKTHROUGH_ROOT,
    CURRENT_REFERENCE_ROOT,
    PRODUCT_AND_DOMAIN_SPEC_ROOT,
    GENERATED_REFERENCE_ROOT,
)

# Tracked Markdown that may sit directly under the repository root.
# plan_26_08_2026.md stays until its plan items close.
REPO_ROOT_MARKDOWN_ALLOWLIST = frozenset(
    {
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "plan_26_08_2026.md",
    }
)


def load_tracked_paths(root: Path) -> set[str] | None:
    """Return Git-tracked paths, or ``None`` when the inventory is unavailable."""

    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if listed.returncode != 0:
        return None
    return {
        raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for raw in listed.stdout.split(b"\0")
        if raw
    }


def _tracked_root_markdown(tracked_paths: Iterable[str]) -> set[str]:
    root_docs: set[str] = set()
    for raw_path in tracked_paths:
        relative = raw_path.replace("\\", "/")
        path = PurePosixPath(relative)
        if path.parent == PurePosixPath("docs") and path.suffix.lower() == ".md":
            root_docs.add(relative)
    return root_docs


def check_root_markdown_placement(tracked_paths: Iterable[str]) -> list[str]:
    """Report missing allowlisted pages and unexpected tracked root pages."""

    actual = _tracked_root_markdown(tracked_paths)
    missing = sorted(ROOT_MARKDOWN_ALLOWLIST - actual)
    unexpected = sorted(actual - ROOT_MARKDOWN_ALLOWLIST)
    return [
        *(f"missing allowed root Markdown: {path}" for path in missing),
        *(f"unexpected tracked root Markdown: {path}" for path in unexpected),
    ]


def _tracked_repo_root_markdown(tracked_paths: Iterable[str]) -> set[str]:
    root_docs: set[str] = set()
    for raw_path in tracked_paths:
        relative = raw_path.replace("\\", "/")
        path = PurePosixPath(relative)
        if path.parent == PurePosixPath(".") and path.suffix.lower() == ".md":
            root_docs.add(relative)
    return root_docs


def check_repo_root_markdown_placement(tracked_paths: Iterable[str]) -> list[str]:
    """Report missing allowlisted pages and unexpected tracked repo-root pages."""

    actual = _tracked_repo_root_markdown(tracked_paths)
    missing = sorted(REPO_ROOT_MARKDOWN_ALLOWLIST - actual)
    unexpected = sorted(actual - REPO_ROOT_MARKDOWN_ALLOWLIST)
    return [
        *(f"missing allowed repository-root Markdown: {path}" for path in missing),
        *(f"unexpected tracked repository-root Markdown: {path}" for path in unexpected),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("docs root placement: FAIL")
        print("git ls-files inventory unavailable")
        return 1

    problems = [
        *check_root_markdown_placement(tracked),
        *check_repo_root_markdown_placement(tracked),
    ]
    if problems:
        print("docs root placement: FAIL")
        for problem in problems:
            print(problem)
        return 1

    print(
        "docs root placement: OK "
        f"({len(ROOT_MARKDOWN_ALLOWLIST)} docs/ files, "
        f"{len(REPO_ROOT_MARKDOWN_ALLOWLIST)} repository-root files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
