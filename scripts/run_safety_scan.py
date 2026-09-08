"""Run Safety once per requirements bucket with scope-bound ignores."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_trivy_policy import validate_waiver

EXIT_SCAN_FAILED = 1
EXIT_NO_BUCKETS = 2
EXIT_BUCKET_MISSING_OR_EMPTY = 3
EXIT_WAIVER_SCOPE_UNSCANNED = 4
EXIT_DUPLICATE_SAFETY_ID = 5
EXIT_MALFORMED_WAIVERS = 6
EXIT_NONCANONICAL_BUCKET = 7

_BUCKET_NAME = re.compile(r"^requirements-(.+)\.txt$")
_SAFETY_ID_FORMAT = re.compile(r"^(?:SFTY-\d+(?:-\d+)*|\d+)$")
_EXPIRES_ON_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class SafetyScanError(Exception):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _today() -> date:
    return datetime.now(UTC).date()


def scope_for_bucket(path: Path) -> str:
    match = _BUCKET_NAME.match(path.name)
    if match is None:
        raise SafetyScanError(
            f"bucket file name is not requirements-<scope>.txt: {path.name}",
            EXIT_NONCANONICAL_BUCKET,
        )
    return match.group(1)


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise SafetyScanError(
            f"malformed waiver file: cannot decode {path}: {exc}",
            EXIT_MALFORMED_WAIVERS,
        ) from exc
    except OSError as exc:
        raise SafetyScanError(
            f"malformed waiver file: cannot read {path}: {exc}",
            EXIT_MALFORMED_WAIVERS,
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SafetyScanError(
            f"malformed waiver file: invalid JSON: {exc}",
            EXIT_MALFORMED_WAIVERS,
        ) from exc
    if not isinstance(payload, dict):
        raise SafetyScanError(
            "malformed waiver file: top-level value must be an object",
            EXIT_MALFORMED_WAIVERS,
        )
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise SafetyScanError(
            f"malformed waiver file: unsupported schema_version {schema_version!r}; expected 1",
            EXIT_MALFORMED_WAIVERS,
        )
    scopes = payload.get("scopes")
    if not isinstance(scopes, dict):
        raise SafetyScanError(
            "malformed waiver file: missing object field 'scopes'",
            EXIT_MALFORMED_WAIVERS,
        )
    for scope_name, scope in scopes.items():
        if not isinstance(scope, dict):
            raise SafetyScanError(
                f"malformed waiver file: scope {scope_name!r} must be an object",
                EXIT_MALFORMED_WAIVERS,
            )
        waivers = scope.get("waivers")
        if not isinstance(waivers, list):
            raise SafetyScanError(
                f"malformed waiver file: scope {scope_name!r} waivers must be a list",
                EXIT_MALFORMED_WAIVERS,
            )
        for waiver in waivers:
            if not isinstance(waiver, dict):
                raise SafetyScanError(
                    f"malformed waiver file: waiver in scope {scope_name!r} must be an object",
                    EXIT_MALFORMED_WAIVERS,
                )
            try:
                validate_waiver(waiver)
            except ValueError as exc:
                raise SafetyScanError(
                    f"malformed waiver file: invalid waiver in scope {scope_name!r}: {exc}",
                    EXIT_MALFORMED_WAIVERS,
                ) from exc
            _validated_safety_id(waiver, str(scope_name))
    return payload


def _validated_safety_id(waiver: dict[str, Any], scope_name: str) -> str | None:
    """Return safety_id when present and valid; None when the key is absent."""
    if "safety_id" not in waiver:
        return None
    safety_id = waiver["safety_id"]
    if not isinstance(safety_id, str) or not _SAFETY_ID_FORMAT.fullmatch(safety_id):
        raise SafetyScanError(
            f"malformed waiver file: safety_id {safety_id!r} in scope {scope_name!r} "
            "must be a non-empty string of the form SFTY-<digits> or a numeric id",
            EXIT_MALFORMED_WAIVERS,
        )
    expires_on = waiver.get("expires_on")
    if not isinstance(expires_on, str) or not _EXPIRES_ON_FORMAT.fullmatch(expires_on):
        raise SafetyScanError(
            f"malformed waiver file: safety_id {safety_id} in scope {scope_name!r} "
            f"has invalid expires_on {expires_on!r}; expected YYYY-MM-DD",
            EXIT_MALFORMED_WAIVERS,
        )
    try:
        date.fromisoformat(expires_on)
    except ValueError as exc:
        raise SafetyScanError(
            f"malformed waiver file: safety_id {safety_id} has invalid expires_on {expires_on!r}",
            EXIT_MALFORMED_WAIVERS,
        ) from exc
    return safety_id


def _safety_ids_by_scope(policy: dict[str, Any]) -> dict[str, list[str]]:
    by_scope: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for scope_name, scope in policy["scopes"].items():
        ids: list[str] = []
        for waiver in scope["waivers"]:
            if "safety_id" not in waiver:
                continue
            token = waiver["safety_id"]
            if token in seen:
                duplicates.append(token)
            else:
                seen[token] = str(scope_name)
            ids.append(token)
        by_scope[str(scope_name)] = ids
    if duplicates:
        unique = ", ".join(dict.fromkeys(duplicates))
        raise SafetyScanError(
            f"duplicate safety_id across scopes: {unique}",
            EXIT_DUPLICATE_SAFETY_ID,
        )
    return by_scope


def _active_ignores(
    policy: dict[str, Any],
    scope_name: str,
    as_of: date,
) -> list[str]:
    scope = policy["scopes"].get(scope_name)
    if not isinstance(scope, dict):
        return []
    applied: list[str] = []
    for waiver in scope["waivers"]:
        if "safety_id" not in waiver:
            continue
        safety_id = waiver["safety_id"]
        expires_on = date.fromisoformat(waiver["expires_on"])
        if expires_on <= as_of:
            continue
        applied.append(safety_id)
    return applied


def _validate_buckets(paths: Sequence[Path]) -> None:
    problems: list[str] = []
    for path in paths:
        if not path.is_file():
            problems.append(str(path))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            problems.append(str(path))
            continue
        if not text.strip():
            problems.append(str(path))
    if problems:
        listed = ", ".join(problems)
        raise SafetyScanError(
            f"bucket file missing or empty: {listed}",
            EXIT_BUCKET_MISSING_OR_EMPTY,
        )


def _validate_waiver_scopes(
    ids_by_scope: dict[str, list[str]],
    scanned_scopes: set[str],
) -> None:
    for scope_name, safety_ids in ids_by_scope.items():
        if not safety_ids:
            continue
        if scope_name in scanned_scopes:
            continue
        listed = ", ".join(safety_ids)
        raise SafetyScanError(
            f"waiver safety_id {listed} in scope {scope_name} maps to no scanned bucket",
            EXIT_WAIVER_SCOPE_UNSCANNED,
        )


def _safety_command(
    safety_cmd: str,
    ignores: Sequence[str],
    bucket: Path,
) -> list[str]:
    command = [safety_cmd, "check"]
    for safety_id in ignores:
        command.extend(["--ignore", safety_id])
    command.extend(["-r", str(bucket)])
    return command


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--waivers",
        type=Path,
        default=Path("security/trivy-waivers.json"),
    )
    parser.add_argument(
        "-r",
        "--requirements",
        action="append",
        type=Path,
        default=[],
        dest="requirements",
    )
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--safety-cmd", default="safety")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    runner: Runner = subprocess.run,
) -> int:
    args = _parse_args(argv)
    buckets: list[Path] = list(args.requirements)
    if not buckets:
        print(
            "no requirements buckets given; pass one or more -r/--requirements",
            file=sys.stderr,
        )
        return EXIT_NO_BUCKETS

    try:
        policy = _load_policy(args.waivers)
        ids_by_scope = _safety_ids_by_scope(policy)
        _validate_buckets(buckets)
        scanned = {scope_for_bucket(path) for path in buckets}
        _validate_waiver_scopes(ids_by_scope, scanned)
    except SafetyScanError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code

    as_of: date = args.as_of or _today()
    failed: list[str] = []
    summaries: list[str] = []
    for bucket in buckets:
        scope_name = scope_for_bucket(bucket)
        ignores = _active_ignores(policy, scope_name, as_of)
        command = _safety_command(args.safety_cmd, ignores, bucket)
        print(f"Safety bucket: {bucket} (scope={scope_name})", flush=True)
        try:
            result = runner(command)
        except OSError as exc:
            print(
                f"failed to start Safety for {bucket}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            ignore_text = ", ".join(ignores) if ignores else "(none)"
            summaries.append(f"  {bucket.name}: FAIL  ignores: {ignore_text}")
            failed.append(bucket.name)
            continue
        passed = result.returncode == 0
        status = "PASS" if passed else "FAIL"
        ignore_text = ", ".join(ignores) if ignores else "(none)"
        summaries.append(f"  {bucket.name}: {status}  ignores: {ignore_text}")
        if not passed:
            failed.append(bucket.name)

    print("Safety scan summary:")
    for line in summaries:
        print(line)
    if failed:
        print("failed buckets: " + ", ".join(failed), file=sys.stderr)
        return EXIT_SCAN_FAILED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
