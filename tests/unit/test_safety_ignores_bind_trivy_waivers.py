import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
import yaml

from tests.unit import test_security_workflow as security_workflow

ROOT = Path(__file__).resolve().parents[2]
HTTPLIB2_SAFETY_ID = "SFTY-20260724-05622"
SCANNER = "scripts/run_safety_scan.py"
WAIVERS_PATH = "security/trivy-waivers.json"
SCANNER_PREFIX = ("python", SCANNER, "--waivers", WAIVERS_PATH)
# Workflow order of SAFETY_BUCKETS. The set is owned by test_security_workflow;
# the sequence is the Run Safety whitelist contract.
CANONICAL_BUCKET_ORDER = (
    "requirements-main.txt",
    "requirements-sdk.txt",
    "requirements-integrations.txt",
    "requirements-extra-cloud.txt",
    "requirements-extra-postgres.txt",
    "requirements-extra-integrations.txt",
    "requirements-flink-runtime.txt",
    "requirements-extra-load.txt",
    "requirements-extra-contract.txt",
)
# Full token only: the ID must end at whitespace, a shell continuation, or EOL.
# A suffix such as `SFTY-…TYPO` must not count as an active ignore.
IGNORE_RE = re.compile(r"--ignore\s+([^\s\\]+)(?=\s|\\|$)")


def _run_safety_step() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    )
    step = next(
        item for item in workflow["jobs"]["safety"]["steps"] if item.get("name") == "Run Safety"
    )
    run = step["run"]
    assert isinstance(run, str)
    return run


def _waivers() -> list[dict]:
    policy = json.loads((ROOT / "security" / "trivy-waivers.json").read_text(encoding="utf-8"))
    waivers: list[dict] = []
    for scope in policy["scopes"].values():
        waivers.extend(scope.get("waivers") or [])
    return waivers


def _executable_lines(run: str) -> list[str]:
    """Non-empty, non-comment lines of the Run Safety step."""
    lines: list[str] = []
    for raw in run.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _joined_executable(run: str) -> str:
    return " ".join(line.rstrip("\\").strip() for line in _executable_lines(run))


def _executable_commands(run: str) -> list[list[str]]:
    """Tokenize executable commands, folding shell line continuations."""
    commands: list[list[str]] = []
    pending: list[str] = []
    for line in _executable_lines(run):
        continued = line.endswith("\\")
        pending.append(line.rstrip("\\").strip())
        if not continued:
            commands.append(" ".join(pending).split())
            pending = []
    if pending:
        commands.append(" ".join(pending).split())
    return commands


def _ignore_ids(run: str) -> list[str]:
    return IGNORE_RE.findall("\n".join(_executable_lines(run)))


def _bound_safety_ids(waivers: list[dict] | None = None) -> set[str]:
    source = waivers if waivers is not None else _waivers()
    return {str(waiver["safety_id"]) for waiver in source if waiver.get("safety_id")}


def _comment_header_id(line: str, safety_ids: set[str]) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    rest = stripped.lstrip("#").strip()
    if not rest:
        return None
    first = rest.split(None, 1)[0]
    if first in safety_ids:
        return first
    return None


def _comment_blocks(run: str, safety_ids: set[str] | None = None) -> dict[str, str]:
    """Map each bound safety_id comment header to its block (until the next header or code)."""
    ids = safety_ids if safety_ids is not None else _bound_safety_ids()
    blocks: dict[str, list[str]] = {}
    current_id: str | None = None
    for line in run.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped.startswith("#"):
            current_id = None
            continue
        header_id = _comment_header_id(line, ids)
        if header_id is not None:
            current_id = header_id
            blocks[current_id] = [line]
            continue
        if current_id is not None:
            blocks[current_id].append(line)
    return {safety_id: "".join(parts) for safety_id, parts in blocks.items()}


def _canonical_scanner_argv() -> list[str]:
    assert set(CANONICAL_BUCKET_ORDER) == set(security_workflow.SAFETY_BUCKETS), (
        "CANONICAL_BUCKET_ORDER must be exactly SAFETY_BUCKETS in workflow order"
    )
    argv = list(SCANNER_PREFIX)
    for bucket in CANONICAL_BUCKET_ORDER:
        argv.extend(["-r", f"{security_workflow.SAFETY_WORK_DIR}/{bucket}"])
    return argv


def _assert_ignores_bind_trivy_waivers(run: str, waivers: list[dict] | None = None) -> None:
    commands = _executable_commands(run)
    assert len(commands) == 1, (
        "Run Safety run block must parse to exactly one executable command; "
        f"found {len(commands)}: {commands}"
    )
    canonical = _canonical_scanner_argv()
    assert commands[0] == canonical, (
        f"Run Safety command must equal the canonical scanner argv {canonical}; got {commands[0]}"
    )

    ignore_ids = _ignore_ids(run)
    assert not ignore_ids, (
        "Run Safety must not pass --ignore; each ignore is derived from the waiver file "
        f"per bucket, not: {ignore_ids}"
    )

    source = waivers if waivers is not None else _waivers()
    bound = [waiver for waiver in source if waiver.get("safety_id")]
    safety_ids = [str(waiver["safety_id"]) for waiver in bound]
    blocks = _comment_blocks(run, set(safety_ids))
    safety_counts = Counter(safety_ids)
    duplicate_safety_ids = sorted(
        safety_id for safety_id, count in safety_counts.items() if count > 1
    )

    assert not duplicate_safety_ids, (
        f"waiver safety_id must be unique, duplicates: {duplicate_safety_ids}"
    )

    for waiver in bound:
        safety_id = str(waiver["safety_id"])
        expires_on = date.fromisoformat(str(waiver["expires_on"]))
        assert expires_on > date.today(), (
            f"waiver {safety_id} expired on {waiver['expires_on']}; drop the Safety ignore"
        )
        block = blocks.get(safety_id)
        assert block is not None, f"Run Safety must have a comment block headed by {safety_id}"
        assert safety_id in block, f"comment block for {safety_id} must mention that id"
        assert str(waiver["expires_on"]) in block, (
            f"comment block for {safety_id} must mention expiry {waiver['expires_on']}"
        )


def _insert_executable_ignore(run: str, ignore_id: str) -> str:
    needle = SCANNER
    assert needle in run
    return run.replace(needle, f"{needle} --ignore {ignore_id}", 1)


def test_safety_ignores_bind_trivy_waivers() -> None:
    _assert_ignores_bind_trivy_waivers(_run_safety_step())


def test_commented_ignore_is_not_an_active_argument() -> None:
    """F-T-21-1: a comment-only `--ignore` must not bind the waiver."""
    run = "          # --ignore 88512 \\\n" + _run_safety_step()
    assert "88512" not in _ignore_ids(run)
    _assert_ignores_bind_trivy_waivers(run)
    bound = [waiver for waiver in _waivers() if waiver.get("safety_id")]
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(
            run,
            waivers=[*bound, {"safety_id": "88512", "expires_on": "2099-01-01"}],
        )


def test_ignore_id_requires_token_boundary() -> None:
    """F-T-21-1: `SFTY-…TYPO` must not count as the real ignore id."""
    run = _insert_executable_ignore(_run_safety_step(), f"{HTTPLIB2_SAFETY_ID}TYPO")
    assert HTTPLIB2_SAFETY_ID not in _ignore_ids(run)
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_expiry_must_live_in_matching_sfty_comment_block() -> None:
    """F-T-21-2: a date in another SFTY block must not satisfy this waiver."""
    run = _run_safety_step()
    blocks = _comment_blocks(run)
    httplib2_block = blocks[HTTPLIB2_SAFETY_ID]
    assert "2026-10-27" in httplib2_block
    mutated_block = httplib2_block.replace("2026-10-27", "DATE-REMOVED")
    mutated_run = run.replace(httplib2_block, mutated_block, 1)
    pyarrow_id = "SFTY-20260217-93940"
    assert "2026-10-27" in _comment_blocks(mutated_run)[pyarrow_id]
    assert "2026-10-27" not in _comment_blocks(mutated_run)[HTTPLIB2_SAFETY_ID]
    with pytest.raises(AssertionError, match=HTTPLIB2_SAFETY_ID):
        _assert_ignores_bind_trivy_waivers(mutated_run)


def test_numeric_ignore_must_bind_a_waiver() -> None:
    """F-T-21-3: a numeric Safety ignore must not bypass the binding check."""
    run = _insert_executable_ignore(_run_safety_step(), "88512")
    assert "88512" in _ignore_ids(run)
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_duplicate_safety_id_and_duplicate_ignore_are_rejected() -> None:
    """F-T-21-4: matching frequencies of a duplicated id must not bind."""
    run = _run_safety_step()
    bound = [waiver for waiver in _waivers() if waiver.get("safety_id")]
    httplib2 = next(waiver for waiver in bound if str(waiver["safety_id"]) == HTTPLIB2_SAFETY_ID)
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run, waivers=[*bound, httplib2])


def test_direct_safety_check_invocation_is_rejected() -> None:
    """F-T-21-5: a smuggled `safety check --ignore` must fail closed."""
    run = (
        _run_safety_step().rstrip()
        + "\n          safety check --ignore 88512 -r requirements-other.txt\n"
    )
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_echo_prefix_is_not_a_scanner_invocation() -> None:
    """F-T-25-1: `echo python scripts/run_safety_scan.py` must not bind."""
    run = _run_safety_step().replace(
        f"python {SCANNER}",
        f"echo python {SCANNER}",
        1,
    )
    assert SCANNER in _joined_executable(run)
    assert WAIVERS_PATH in _joined_executable(run)
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_additional_scanner_invocation_is_rejected() -> None:
    """F-T-25-1: a second python scanner invocation must fail closed."""
    run = (
        _run_safety_step().rstrip()
        + f"\n          python {SCANNER} --waivers {WAIVERS_PATH} "
        + "-r requirements-other.txt\n"
    )
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_marker_args_on_another_command_do_not_bind() -> None:
    """F-T-25-1: --waivers / scanner path on a different command is drift."""
    run = f"          python other.py --waivers {WAIVERS_PATH}\n" + _run_safety_step()
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_safety_cmd_override_is_rejected() -> None:
    """F-T-25-7: `--safety-cmd true` must not disable the scanner."""
    run = _run_safety_step().rstrip() + " --safety-cmd true\n"
    with pytest.raises(AssertionError, match="--safety-cmd"):
        _assert_ignores_bind_trivy_waivers(run)


def test_as_of_override_is_rejected() -> None:
    """F-T-25-7: `--as-of` must not backdate waiver expiry in CI."""
    run = _run_safety_step().rstrip() + " --as-of 2000-01-01\n"
    with pytest.raises(AssertionError, match="--as-of"):
        _assert_ignores_bind_trivy_waivers(run)


def test_second_waivers_argument_is_rejected() -> None:
    """F-T-25-7: a second `--waivers` must not replace the reviewed file."""
    run = _run_safety_step().rstrip() + " --waivers unreviewed.json\n"
    with pytest.raises(AssertionError, match="--waivers"):
        _assert_ignores_bind_trivy_waivers(run)


def test_errexit_disabled_wrapper_is_rejected() -> None:
    """F-T-25-11: `set +e` before the scanner and `true` after must fail closed."""
    run = "          set +e\n" + _run_safety_step().rstrip() + "\n          true\n"
    with pytest.raises(AssertionError):
        _assert_ignores_bind_trivy_waivers(run)


def test_numeric_safety_id_comment_header_binds() -> None:
    """F-T-21-6: bound safety_id values, including numeric ids, head comment blocks."""
    expires_on = "2099-01-01"
    run = _run_safety_step()
    header = f"# 88512 numeric advisory expires {expires_on}\n"
    lines = run.splitlines(keepends=True)
    inserted: list[str] = []
    placed = False
    for line in lines:
        if not placed and SCANNER in line:
            inserted.append(header)
            placed = True
        inserted.append(line)
    assert placed, "expected the scanner invocation to attach the numeric comment header"
    run = "".join(inserted)
    bound = [waiver for waiver in _waivers() if waiver.get("safety_id")]
    synthetic = {"safety_id": "88512", "expires_on": expires_on}
    _assert_ignores_bind_trivy_waivers(run, waivers=[*bound, synthetic])
