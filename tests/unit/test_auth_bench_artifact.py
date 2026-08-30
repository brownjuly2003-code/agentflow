from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from scripts.perf import auth_bench

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_RECORD = ROOT / "docs" / "perf" / "auth-bench-2026-05-26.md"
LIFECYCLE_PAGE = ROOT / "docs" / "perf" / "auth-bench.md"
HISTORICAL_SHA256 = "da2ba9f6e47da56bb3d982ed4b435e58c78b602ec20dea1e1e2cb3c272fec9ad"


def test_parse_args_defaults_to_ignored_runtime_artifact(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["auth_bench.py"])

    args = auth_bench.parse_args()

    assert args.report == str(
        auth_bench.PROJECT_ROOT / ".artifacts" / "perf" / "auth-bench-current.md"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "report_path",
    [
        "docs/perf/auth-bench.md",
        str(LIFECYCLE_PAGE),
        "docs/perf/auth-bench-2026-05-26.md",
        str(HISTORICAL_RECORD),
    ],
)
def test_tracked_auth_docs_cannot_be_overwritten(report_path: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/perf"):
        auth_bench.resolve_report_path(report_path)


def test_relative_report_path_resolves_from_project_root() -> None:
    assert auth_bench.resolve_report_path(".artifacts/perf/custom.md") == (
        auth_bench.PROJECT_ROOT / ".artifacts" / "perf" / "custom.md"
    )


def test_legacy_lookup_requests_bcrypt_explicitly(monkeypatch) -> None:
    tokens = iter(("known-key", "bogus-key"))
    hash_calls: list[tuple[int, str]] = []

    monkeypatch.setattr(auth_bench.secrets, "token_urlsafe", lambda _size: next(tokens))

    def fake_hash(value: str, rounds: int, scheme: str) -> str:
        hash_calls.append((rounds, scheme))
        return f"hash:{value}"

    monkeypatch.setattr(auth_bench, "hash_api_key", fake_hash)
    monkeypatch.setattr(
        auth_bench,
        "verify_api_key",
        lambda value, key_hash: key_hash == f"hash:{value}",
    )

    auth_bench._bench_authenticate_o_n_lookup(rounds=12, n_keys=1, trials=1)

    assert hash_calls == [(12, "bcrypt")]


def test_main_rejects_historical_record_before_benchmark_work(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["auth_bench.py", "--report", "docs/perf/auth-bench-2026-05-26.md"],
    )

    def fail_if_benchmark_runs(*_args, **_kwargs):
        pytest.fail("tracked-output validation must run before benchmark work")

    monkeypatch.setattr(auth_bench, "_bench_authenticate_o_n_lookup", fail_if_benchmark_runs)
    monkeypatch.setattr(auth_bench, "_bench_rate_window_trim", fail_if_benchmark_runs)

    assert auth_bench.main() == 2
    assert ".artifacts/perf" in capsys.readouterr().err


def test_main_writes_bounded_runtime_report(monkeypatch, tmp_path, capsys) -> None:
    output_path = tmp_path / "auth-bench.md"
    monkeypatch.setattr(sys, "argv", ["auth_bench.py", "--report", str(output_path)])
    monkeypatch.setattr(
        auth_bench,
        "_bench_authenticate_o_n_lookup",
        lambda **_kwargs: print("legacy-auth-sample"),
    )
    monkeypatch.setattr(
        auth_bench,
        "_bench_rate_window_trim",
        lambda **_kwargs: print("rate-window-sample"),
    )

    assert auth_bench.main() == 0

    report = output_path.read_text(encoding="utf-8")
    assert report.startswith("# Auth benchmark runtime artifact\n")
    assert "explicit legacy bcrypt" in report
    assert "not a production SLA" in report
    assert "legacy-auth-sample" in report
    assert "rate-window-sample" in report
    assert f"wrote {output_path}" in capsys.readouterr().out


def test_auth_benchmark_docs_name_owner_output_and_promotion_boundary() -> None:
    lifecycle = (ROOT / "docs" / "perf" / "auth-bench.md").read_text(encoding="utf-8")
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "python scripts/perf/auth_bench.py" in lifecycle
    assert ".artifacts/perf/auth-bench-current.md" in lifecycle
    assert "auth-bench-2026-05-26.md" in lifecycle
    assert "explicit legacy bcrypt" in lifecycle
    assert "date-stamped" in lifecycle
    assert "| Authentication legacy-path benchmark |" in docs_hub
    assert "scripts/perf/auth_bench.py" in perf_hub
    assert ".artifacts/perf/auth-bench-current.md" in perf_hub
    assert "python scripts/perf/auth_bench.py" in contributing
    assert "Auth legacy-path benchmark artifact sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_historical_auth_record_keeps_published_digest() -> None:
    assert hashlib.sha256(HISTORICAL_RECORD.read_bytes()).hexdigest() == HISTORICAL_SHA256
