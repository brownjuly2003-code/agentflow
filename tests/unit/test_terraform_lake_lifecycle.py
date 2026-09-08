"""S3 lifecycle must not put an age clock on Iceberg objects (audit FB-11).

The lake bucket's lifecycle configuration shipped two rules that deleted by age
under `warehouse/`: `raw-data-lifecycle` (GLACIER after 90 days, expiration
after 365, on `warehouse/raw/`) and `iceberg-metadata` (expiration after 30 days
on `warehouse/metadata/`, under a comment claiming it kept 30 days of
snapshots).

Neither prefix matched anything. Iceberg lays tables out as
`<warehouse>/<namespace>/<table>/{metadata,data}/...` and the configured
namespace is `agentflow` (`config/iceberg.yaml`), so both rules were no-ops
wearing the language of a retention policy. That is the trap rather than the
bug: the next person to notice they delete nothing reaches for the prefix the
Flink sink actually writes (`warehouse/`, `modules/flink/main.tf`), and the
no-op becomes a job that removes manifest lists and data files that current
snapshots reference. A file's age says nothing about whether a live snapshot
still names it, so the outcome is not a cleaned table -- it is one that reads
`NoSuchKey`.

`terraform-apply.yml` has been disabled since 2026-04-23, which is exactly why
this is worth pinning: reference topology someone is expected to switch on, and
by then the trap costs data rather than a review comment. Snapshot expiry
belongs to the catalog (`iceberg_snapshot_expiry` in
`src/agentflow_runtime/orchestration/dags/daily_batch.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_ROOT = PROJECT_ROOT / "infrastructure" / "terraform"
STORAGE_MAIN = TERRAFORM_ROOT / "modules" / "storage" / "main.tf"
ROOT_MAIN = TERRAFORM_ROOT / "main.tf"
ROOT_VARIABLES = TERRAFORM_ROOT / "variables.tf"
TFVARS_FILES = (
    TERRAFORM_ROOT / "dev.tfvars",
    TERRAFORM_ROOT / "environments" / "prod.tfvars.example",
    TERRAFORM_ROOT / "environments" / "staging.tfvars.example",
)

# Anything an Iceberg snapshot can still be pointing at.
TABLE_DATA_PREFIX = "warehouse/"


def _block_body(text: str, header: str) -> str:
    """Return the body of the first ``header {`` block, brace-matched.

    A regex cannot do this: rules nest `filter`, `expiration` and friends, so
    the closing brace has to be counted rather than searched for.
    """
    start = text.index(header)
    open_brace = text.index("{", start)
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : index]
    raise AssertionError(f"unbalanced braces after {header!r}")


def _rule_blocks(lifecycle_body: str) -> list[str]:
    blocks: list[str] = []
    cursor = 0
    pattern = re.compile(r"^\s*rule\s*\{", re.MULTILINE)
    while True:
        match = pattern.search(lifecycle_body, cursor)
        if match is None:
            return blocks
        body = _block_body(lifecycle_body[match.start() :], "rule")
        blocks.append(body)
        cursor = match.start() + len(body)


@pytest.fixture(scope="module")
def lifecycle_rules() -> list[str]:
    text = STORAGE_MAIN.read_text(encoding="utf-8")
    body = _block_body(text, 'resource "aws_s3_bucket_lifecycle_configuration" "lake"')
    rules = _rule_blocks(body)
    assert rules, "no lifecycle rules parsed -- the parser, not the module, is wrong"
    return rules


def _rule_id(rule: str) -> str:
    match = re.search(r'id\s*=\s*"([^"]+)"', rule)
    assert match is not None, rule
    return match.group(1)


def _prefix(rule: str) -> str | None:
    match = re.search(r'prefix\s*=\s*"([^"]*)"', rule)
    return None if match is None else match.group(1)


def test_the_parser_sees_every_rule(lifecycle_rules: list[str]) -> None:
    """Guard the guard: a parser that silently returned one block would make
    every assertion below vacuously true."""
    ids = [_rule_id(rule) for rule in lifecycle_rules]

    assert len(ids) == len(set(ids))
    assert "checkpoint-cleanup" in ids


def test_no_rule_expires_objects_under_the_warehouse_prefix(
    lifecycle_rules: list[str],
) -> None:
    offenders = [
        _rule_id(rule)
        for rule in lifecycle_rules
        if (_prefix(rule) or "").startswith(TABLE_DATA_PREFIX) and "expiration {" in rule
    ]

    assert offenders == [], (
        f"lifecycle rules {offenders} expire objects under {TABLE_DATA_PREFIX!r} on an age "
        "clock. Iceberg retention is snapshot-scoped and belongs to the catalog "
        "(expire_snapshots / remove_orphan_files); S3 expiration here deletes files that "
        "live snapshots still reference and leaves the table unreadable."
    )


def test_no_rule_transitions_warehouse_objects_to_an_archive_class(
    lifecycle_rules: list[str],
) -> None:
    """Not deleting is not enough: GLACIER needs a restore before a read, so a
    transitioned data file fails the query it was archived out of."""
    offenders = [
        _rule_id(rule)
        for rule in lifecycle_rules
        if (_prefix(rule) or "").startswith(TABLE_DATA_PREFIX) and "transition {" in rule
    ]

    assert offenders == []


def test_the_surviving_rules_only_touch_what_s3_owns(lifecycle_rules: list[str]) -> None:
    """Two things age out on their own clock: Flink's scratch checkpoints, and
    the noncurrent versions this versioned bucket accrues. A current object is
    never a noncurrent version, so the second rule cannot reach live data."""
    by_id = {_rule_id(rule): rule for rule in lifecycle_rules}

    assert set(by_id) == {"checkpoint-cleanup", "noncurrent-version-cleanup"}
    assert _prefix(by_id["checkpoint-cleanup"]) == "checkpoints/"

    noncurrent = by_id["noncurrent-version-cleanup"]
    assert "noncurrent_version_expiration {" in noncurrent
    assert "expiration {" not in noncurrent.replace("noncurrent_version_expiration {", "")


def test_the_retired_age_knobs_are_gone_everywhere() -> None:
    """A variable that no longer drives anything is worse than no variable: the
    tfvars still read like retention policy while nothing enforces it."""
    retired = ("storage_glacier_after_days", "storage_expire_after_days")
    sources = [ROOT_MAIN, ROOT_VARIABLES, STORAGE_MAIN, *TFVARS_FILES]

    for path in sources:
        text = path.read_text(encoding="utf-8")
        for name in retired:
            assert name not in text, f"{path.relative_to(PROJECT_ROOT)} still names {name}"

    module_text = STORAGE_MAIN.read_text(encoding="utf-8")
    assert "lifecycle_expire_days" not in module_text
    assert "lifecycle_glacier_days" not in module_text


def test_every_tfvars_file_sets_the_variable_the_module_now_takes() -> None:
    for path in TFVARS_FILES:
        assert "storage_noncurrent_version_expire_days" in path.read_text(encoding="utf-8"), path


def test_the_module_points_at_the_catalog_for_table_retention() -> None:
    """The comment is load-bearing: the next person who wants a retention policy
    has to be told where it actually lives, or the rule comes back."""
    text = STORAGE_MAIN.read_text(encoding="utf-8")

    assert "expire_snapshots" in text
    assert "daily_batch.py" in text
