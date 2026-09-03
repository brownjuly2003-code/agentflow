from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts.run_safety_scan import (
    EXIT_MALFORMED_WAIVERS,
    SafetyScanError,
    _load_policy,
    main,
    scope_for_bucket,
)

PYARROW_ID = "SFTY-20260217-93940"
HTTPLIB2_ID = "SFTY-20260724-05622"
FLINK_IDS = (HTTPLIB2_ID, PYARROW_ID)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_bucket(path: Path, body: str = "pkg==1.0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _policy(**scope_waivers: list[dict[str, str]]) -> dict:
    scopes = {
        name: {"image": name, "owner": "security", "waivers": waivers}
        for name, waivers in scope_waivers.items()
    }
    if "api-runtime" not in scopes:
        scopes["api-runtime"] = {"image": "agentflow-api", "owner": "security", "waivers": []}
    return {"schema_version": 1, "reviewed_on": "2026-07-27", "scopes": scopes}


def _waiver(
    safety_id: str,
    *,
    expires_on: str = "2026-10-27",
    package: str = "pkg",
) -> dict[str, str]:
    return {
        "id": f"CVE-{safety_id}",
        "safety_id": safety_id,
        "package": package,
        "installed_version": "1.0",
        "fixed_version": "2.0",
        "expires_on": expires_on,
        "disposition": "not_affected",
        "rationale": "test",
        "removal_condition": "remove",
    }


def _ignores(cmd: list[str]) -> list[str]:
    found: list[str] = []
    index = 0
    while index < len(cmd) - 1:
        if cmd[index] == "--ignore":
            found.append(cmd[index + 1])
            index += 2
            continue
        index += 1
    return found


def _bucket_arg(cmd: list[str]) -> str:
    return cmd[cmd.index("-r") + 1]


class FakeRunner:
    def __init__(
        self,
        returncodes: dict[str, int] | None = None,
        errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.returncodes = returncodes or {}
        self.errors = errors or {}
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, object]] = []

    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        self.kwargs.append(dict(kwargs))
        bucket = _bucket_arg(cmd)
        name = Path(bucket).name
        error = self.errors.get(bucket, self.errors.get(name))
        if error is not None:
            raise error
        code = self.returncodes.get(bucket, self.returncodes.get(name, 0))
        return subprocess.CompletedProcess(
            cmd,
            code,
            stdout=f"safety output for {name}\n",
            stderr="",
        )


def _argv(waivers: Path, *buckets: Path, as_of: str | None = "2026-09-02") -> list[str]:
    argv = ["--waivers", str(waivers)]
    if as_of is not None:
        argv.extend(["--as-of", as_of])
    for bucket in buckets:
        argv.extend(["-r", str(bucket)])
    return argv


def test_flink_runtime_receives_only_its_waiver_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(
            **{
                "flink-runtime": [
                    _waiver(HTTPLIB2_ID, package="httplib2"),
                    _waiver(PYARROW_ID, package="pyarrow"),
                ]
            }
        ),
    )
    names = (
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
    buckets = [_write_bucket(tmp_path / name) for name in names]
    runner = FakeRunner()

    code = main(_argv(waivers, *buckets), runner=runner)
    captured = capsys.readouterr()

    assert code == 0
    assert len(runner.calls) == len(buckets)
    assert [Path(_bucket_arg(cmd)).name for cmd in runner.calls] == list(names)
    for cmd, bucket in zip(runner.calls, buckets, strict=True):
        assert cmd[0] == "safety"
        assert cmd[1] == "check"
        assert cmd[-2:] == ["-r", str(bucket)]
        if bucket.name == "requirements-flink-runtime.txt":
            assert _ignores(cmd) == list(FLINK_IDS)
        else:
            assert _ignores(cmd) == []
    assert "::group::" not in captured.out
    assert "PASS" in captured.out
    assert HTTPLIB2_ID in captured.out
    assert PYARROW_ID in captured.out


def test_expired_waiver_is_not_applied(tmp_path: Path) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(
            **{
                "flink-runtime": [
                    _waiver(HTTPLIB2_ID, expires_on="2026-09-01"),
                    _waiver(PYARROW_ID, expires_on="2026-10-27"),
                ]
            }
        ),
    )
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, flink, as_of="2026-09-02"), runner=runner)

    assert code == 0
    assert _ignores(runner.calls[0]) == [PYARROW_ID]


def test_expiry_on_as_of_date_is_not_applied(tmp_path: Path) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(**{"flink-runtime": [_waiver(HTTPLIB2_ID, expires_on="2026-09-02")]}),
    )
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, flink, as_of="2026-09-02"), runner=runner)

    assert code == 0
    assert _ignores(runner.calls[0]) == []


def test_scans_every_bucket_after_an_earlier_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = _write_json(tmp_path / "waivers.json", _policy(**{"flink-runtime": []}))
    first = _write_bucket(tmp_path / "requirements-main.txt")
    second = _write_bucket(tmp_path / "requirements-sdk.txt")
    third = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner({str(first): 2, str(third): 4})

    code = main(_argv(waivers, first, second, third), runner=runner)
    captured = capsys.readouterr()

    assert code == 1
    assert len(runner.calls) == 3
    assert "FAIL" in captured.out
    assert "PASS" in captured.out
    combined = captured.out + captured.err
    assert first.name in combined
    assert third.name in combined
    assert "failed buckets" in combined.lower()


def test_no_requirements_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    waivers = _write_json(tmp_path / "waivers.json", _policy())
    runner = FakeRunner()

    code = main(["--waivers", str(waivers), "--as-of", "2026-09-02"], runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "-r" in captured.err.lower() or "requirements" in captured.err.lower()


def test_missing_bucket_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    waivers = _write_json(tmp_path / "waivers.json", _policy())
    missing = tmp_path / "requirements-main.txt"
    runner = FakeRunner()

    code = main(_argv(waivers, missing), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "missing" in captured.err.lower() or "empty" in captured.err.lower()
    assert missing.name in captured.err


def test_empty_bucket_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    waivers = _write_json(tmp_path / "waivers.json", _policy())
    empty = _write_bucket(tmp_path / "requirements-main.txt", body="  \n")
    runner = FakeRunner()

    code = main(_argv(waivers, empty), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "empty" in captured.err.lower() or "missing" in captured.err.lower()


def test_malformed_waiver_file_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = tmp_path / "waivers.json"
    waivers.write_text("{not json", encoding="utf-8")
    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "malformed" in captured.err.lower()


def test_duplicate_safety_id_across_scopes_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(
            **{
                "flink-runtime": [_waiver(HTTPLIB2_ID)],
                "main": [_waiver(HTTPLIB2_ID)],
            }
        ),
    )
    buckets = [
        _write_bucket(tmp_path / "requirements-main.txt"),
        _write_bucket(tmp_path / "requirements-flink-runtime.txt"),
    ]
    runner = FakeRunner()

    code = main(_argv(waivers, *buckets), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "duplicate" in captured.err.lower()
    assert HTTPLIB2_ID in captured.err


def test_waiver_scope_without_scanned_bucket_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(**{"api-runtime": [_waiver(HTTPLIB2_ID)]}),
    )
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, flink), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "api-runtime" in captured.err
    assert HTTPLIB2_ID in captured.err


def test_scope_absent_from_waiver_file_runs_with_zero_ignores(tmp_path: Path) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(**{"flink-runtime": [_waiver(PYARROW_ID)]}),
    )
    other = _write_bucket(tmp_path / "requirements-main.txt")
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, other, flink), runner=runner)

    assert code == 0
    assert _ignores(runner.calls[0]) == []
    assert _ignores(runner.calls[1]) == [PYARROW_ID]


def test_fail_closed_rules_use_distinct_exit_codes(tmp_path: Path) -> None:
    runner = FakeRunner()
    codes: list[int] = []

    waivers = _write_json(tmp_path / "waivers.json", _policy())
    codes.append(main(["--waivers", str(waivers), "--as-of", "2026-09-02"], runner=runner))

    missing = tmp_path / "requirements-main.txt"
    missing_code = main(_argv(waivers, missing), runner=runner)
    codes.append(missing_code)

    empty = _write_bucket(tmp_path / "requirements-sdk.txt", body="")
    empty_code = main(_argv(waivers, empty), runner=runner)
    assert empty_code == missing_code

    malformed = tmp_path / "bad.json"
    malformed.write_text("[]", encoding="utf-8")
    present = _write_bucket(tmp_path / "requirements-integrations.txt")
    codes.append(main(_argv(malformed, present), runner=runner))

    dup = _write_json(
        tmp_path / "dup.json",
        _policy(**{"flink-runtime": [_waiver(HTTPLIB2_ID)], "main": [_waiver(HTTPLIB2_ID)]}),
    )
    main_bucket = _write_bucket(tmp_path / "requirements-main.txt")
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    codes.append(main(_argv(dup, main_bucket, flink), runner=runner))

    moved = _write_json(
        tmp_path / "moved.json",
        _policy(**{"api-runtime": [_waiver(PYARROW_ID)]}),
    )
    codes.append(main(_argv(moved, flink), runner=runner))

    alias = _write_bucket(tmp_path / "flink-runtime.txt")
    codes.append(main(_argv(waivers, alias), runner=runner))

    assert all(code != 0 for code in codes)
    assert len(set(codes)) == len(codes)


@pytest.mark.parametrize("schema_version", [True, "1"], ids=["boolean", "string"])
def test_schema_version_must_be_int_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    schema_version: object,
) -> None:
    payload = _policy()
    payload["schema_version"] = schema_version
    waivers = _write_json(tmp_path / "waivers.json", payload)
    with pytest.raises(SafetyScanError) as excinfo:
        _load_policy(waivers)
    assert excinfo.value.exit_code == EXIT_MALFORMED_WAIVERS
    assert "schema_version" in str(excinfo.value).lower()

    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()
    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code == EXIT_MALFORMED_WAIVERS
    assert runner.calls == []
    assert "malformed" in captured.err.lower()
    assert "schema_version" in captured.err.lower()


def test_non_utf8_waiver_file_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = tmp_path / "waivers.json"
    waivers.write_bytes(b"\xff\xfe not utf-8 {")
    with pytest.raises(SafetyScanError) as excinfo:
        _load_policy(waivers)
    assert excinfo.value.exit_code == EXIT_MALFORMED_WAIVERS
    assert "malformed" in str(excinfo.value).lower()

    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()
    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code == EXIT_MALFORMED_WAIVERS
    assert runner.calls == []
    assert "malformed" in captured.err.lower()


def test_unsupported_schema_version_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _policy()
    payload["schema_version"] = 2
    waivers = _write_json(tmp_path / "waivers.json", payload)
    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "malformed" in captured.err.lower()
    assert "schema_version" in captured.err.lower()


def test_non_list_waivers_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _policy()
    payload["scopes"]["api-runtime"]["waivers"] = {}
    waivers = _write_json(tmp_path / "waivers.json", payload)
    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "malformed" in captured.err.lower()
    assert "waivers" in captured.err.lower()


def test_null_waivers_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _policy()
    payload["scopes"]["api-runtime"]["waivers"] = None
    waivers = _write_json(tmp_path / "waivers.json", payload)
    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "malformed" in captured.err.lower()


def test_noncanonical_bucket_name_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(**{"flink-runtime": [_waiver(HTTPLIB2_ID)]}),
    )
    canonical = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    alias = _write_bucket(tmp_path / "flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, canonical, alias), runner=runner)
    captured = capsys.readouterr()

    assert code != 0
    assert runner.calls == []
    assert "flink-runtime.txt" in captured.err
    assert "requirements-" in captured.err


def test_scope_for_bucket_rejects_stem_fallback() -> None:
    with pytest.raises(SafetyScanError):
        scope_for_bucket(Path("flink-runtime.txt"))
    assert scope_for_bucket(Path("requirements-flink-runtime.txt")) == "flink-runtime"


def test_launch_error_still_scans_remaining_buckets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waivers = _write_json(tmp_path / "waivers.json", _policy(**{"flink-runtime": []}))
    first = _write_bucket(tmp_path / "requirements-main.txt")
    second = _write_bucket(tmp_path / "requirements-sdk.txt")
    runner = FakeRunner(errors={str(first): OSError("safety missing")})

    code = main(_argv(waivers, first, second), runner=runner)
    captured = capsys.readouterr()

    assert code == 1
    assert len(runner.calls) == 2
    combined = captured.out + captured.err
    assert "FAIL" in captured.out
    assert "PASS" in captured.out
    assert first.name in combined
    assert second.name in combined
    assert "failed buckets" in combined.lower()
    assert "Safety scan summary:" in captured.out


def test_runner_does_not_capture_output(tmp_path: Path) -> None:
    waivers = _write_json(tmp_path / "waivers.json", _policy())
    bucket = _write_bucket(tmp_path / "requirements-main.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, bucket), runner=runner)

    assert code == 0
    assert runner.kwargs
    for kwargs in runner.kwargs:
        assert kwargs.get("capture_output") is not True
        assert "capture_output" not in kwargs


@pytest.mark.parametrize(
    "safety_id",
    [False, 0, [], "", {"nested": True}],
    ids=["false", "zero", "list", "empty", "object"],
)
def test_present_invalid_safety_id_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    safety_id: object,
) -> None:
    payload = _policy(**{"flink-runtime": [_waiver(HTTPLIB2_ID)]})
    payload["scopes"]["flink-runtime"]["waivers"][0]["safety_id"] = safety_id
    waivers = _write_json(tmp_path / "waivers.json", payload)
    with pytest.raises(SafetyScanError) as excinfo:
        _load_policy(waivers)
    assert excinfo.value.exit_code == EXIT_MALFORMED_WAIVERS
    assert "safety_id" in str(excinfo.value).lower()

    bucket = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()
    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code == EXIT_MALFORMED_WAIVERS
    assert runner.calls == []
    assert "malformed" in captured.err.lower()
    assert "safety_id" in captured.err.lower()


def test_non_string_expires_on_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _policy(**{"flink-runtime": [_waiver(HTTPLIB2_ID)]})
    payload["scopes"]["flink-runtime"]["waivers"][0]["expires_on"] = 20261027
    waivers = _write_json(tmp_path / "waivers.json", payload)
    with pytest.raises(SafetyScanError) as excinfo:
        _load_policy(waivers)
    assert excinfo.value.exit_code == EXIT_MALFORMED_WAIVERS
    assert "expires_on" in str(excinfo.value).lower()

    bucket = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()
    code = main(_argv(waivers, bucket), runner=runner)
    captured = capsys.readouterr()

    assert code == EXIT_MALFORMED_WAIVERS
    assert runner.calls == []
    assert "malformed" in captured.err.lower()
    assert "expires_on" in captured.err.lower()


def test_absent_safety_id_is_skipped_not_malformed(tmp_path: Path) -> None:
    waiver = _waiver(HTTPLIB2_ID)
    del waiver["safety_id"]
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(**{"flink-runtime": [waiver]}),
    )
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, flink), runner=runner)

    assert code == 0
    assert _ignores(runner.calls[0]) == []


def test_default_as_of_is_today(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.run_safety_scan._today", lambda: date(2026, 10, 27))
    waivers = _write_json(
        tmp_path / "waivers.json",
        _policy(**{"flink-runtime": [_waiver(HTTPLIB2_ID, expires_on="2026-10-27")]}),
    )
    flink = _write_bucket(tmp_path / "requirements-flink-runtime.txt")
    runner = FakeRunner()

    code = main(_argv(waivers, flink, as_of=None), runner=runner)

    assert code == 0
    assert _ignores(runner.calls[0]) == []
