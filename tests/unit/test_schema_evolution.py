from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serving.api.routers.contracts import router as contracts_router
from src.serving.semantic_layer.contract_registry import ContractRegistry
from src.serving.semantic_layer.schema_evolution import EvolutionChecker


def _field(
    name: str,
    field_type: str = "string",
    *,
    required: bool = False,
    description: str | None = None,
    values: list[str] | None = None,
    default: object | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "type": field_type,
        "required": required,
    }
    if description is not None:
        payload["description"] = description
    if values is not None:
        payload["values"] = values
    if default is not None:
        payload["default"] = default
    return payload


def _schema(
    *fields: dict[str, object],
    entity: str = "order",
    version: str = "1",
    status: str = "stable",
) -> dict[str, object]:
    return {
        "entity": entity,
        "version": version,
        "released": "2026-04-11",
        "status": status,
        "fields": list(fields),
        "breaking_changes": [],
    }


def _write_contract(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def _build_contracts_client(contracts_dir: Path) -> TestClient:
    app = FastAPI()
    app.state.catalog = SimpleNamespace(contract_registry=ContractRegistry(contracts_dir))
    app.include_router(contracts_router, prefix="/v1")
    return TestClient(app)


def _run_git(args: list[str], cwd: Path) -> None:
    git_executable = shutil.which("git") or "git"
    subprocess.run(  # noqa: S603,S607
        [git_executable, *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def checker() -> EvolutionChecker:
    return EvolutionChecker()


def test_field_removed_is_breaking(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("order_id", required=True), _field("status", required=True)),
        _schema(_field("order_id", required=True)),
    )

    assert report.is_breaking is True
    assert report.breaking_changes == [
        {"type": "field_removed", "field": "status", "severity": "breaking"},
    ]


def test_field_type_changed_is_breaking(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("total_amount", "float", required=True)),
        _schema(_field("total_amount", "string", required=True)),
    )

    assert report.is_breaking is True
    assert report.breaking_changes == [
        {
            "type": "field_type_changed",
            "field": "total_amount",
            "severity": "breaking",
            "from": "float",
            "to": "string",
        },
    ]


def test_existing_field_becoming_required_is_breaking(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("discount_amount", "float", required=False)),
        _schema(_field("discount_amount", "float", required=True)),
    )

    assert report.is_breaking is True
    assert report.breaking_changes == [
        {
            "type": "field_required_added",
            "field": "discount_amount",
            "severity": "breaking",
        },
    ]


def test_new_required_field_is_breaking(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("order_id", required=True)),
        _schema(
            _field("order_id", required=True),
            _field("currency", required=True),
        ),
    )

    assert report.is_breaking is True
    assert report.breaking_changes == [
        {
            "type": "field_required_added",
            "field": "currency",
            "severity": "breaking",
        },
    ]


def test_enum_value_removed_is_breaking(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(
            _field(
                "status",
                "enum",
                required=True,
                values=["pending", "processing", "shipped"],
            )
        ),
        _schema(
            _field(
                "status",
                "enum",
                required=True,
                values=["pending", "processing"],
            )
        ),
    )

    assert report.is_breaking is True
    assert report.breaking_changes == [
        {
            "type": "enum_value_removed",
            "field": "status",
            "severity": "breaking",
            "values": ["shipped"],
        },
    ]


def test_optional_field_added_is_safe(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("order_id", required=True)),
        _schema(
            _field("order_id", required=True),
            _field("discount_amount", "float", required=False),
        ),
    )

    assert report.is_breaking is False
    assert report.safe_changes == [
        {
            "type": "field_added_optional",
            "field": "discount_amount",
            "severity": "safe",
        },
    ]


def test_description_changed_is_safe(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("order_id", required=True, description="Order identifier")),
        _schema(_field("order_id", required=True, description="Public order identifier")),
    )

    assert report.is_breaking is False
    assert report.safe_changes == [
        {
            "type": "description_changed",
            "field": "order_id",
            "severity": "safe",
        },
    ]


def test_enum_value_added_is_safe(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("status", "enum", required=True, values=["pending", "processing"])),
        _schema(
            _field(
                "status",
                "enum",
                required=True,
                values=["pending", "processing", "shipped"],
            )
        ),
    )

    assert report.is_breaking is False
    assert report.safe_changes == [
        {
            "type": "enum_value_added",
            "field": "status",
            "severity": "safe",
            "values": ["shipped"],
        },
    ]


def test_field_default_added_is_safe(checker: EvolutionChecker) -> None:
    report = checker.check(
        _schema(_field("currency", required=True)),
        _schema(_field("currency", required=True, default="USD")),
    )

    assert report.is_breaking is False
    assert report.safe_changes == [
        {
            "type": "field_default_added",
            "field": "currency",
            "severity": "safe",
            "default": "USD",
        },
    ]


def test_no_changes_is_not_breaking(checker: EvolutionChecker) -> None:
    schema = _schema(_field("order_id", required=True), _field("status", required=True))

    report = checker.check(schema, schema)

    assert report.is_breaking is False
    assert report.breaking_changes == []
    assert report.safe_changes == []


def test_validate_endpoint_reports_breaking_change_and_requires_version_bump(
    tmp_path: Path,
) -> None:
    contracts_dir = tmp_path / "contracts"
    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(
            _field("order_id", required=True),
            _field("status", required=True),
        ),
    )

    with _build_contracts_client(contracts_dir) as client:
        response = client.post(
            "/v1/contracts/order/validate",
            json=_schema(_field("order_id", required=True)),
        )

    assert response.status_code == 200
    assert response.json() == {
        "entity": "order",
        "base_version": "1",
        "candidate_version": "1",
        "breaking_changes": [{"type": "field_removed", "field": "status", "severity": "breaking"}],
        "safe_changes": [],
        "is_breaking": True,
        "requires_version_bump": True,
    }


def test_validate_endpoint_accepts_breaking_change_with_new_version(
    tmp_path: Path,
) -> None:
    contracts_dir = tmp_path / "contracts"
    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(
            _field("order_id", required=True),
            _field("status", required=True),
        ),
    )

    with _build_contracts_client(contracts_dir) as client:
        response = client.post(
            "/v1/contracts/order/validate",
            json=_schema(_field("order_id", required=True), version="2"),
        )

    assert response.status_code == 200
    assert response.json()["is_breaking"] is True
    assert response.json()["requires_version_bump"] is False


def test_schema_check_script_exits_zero_for_safe_change(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo-safe"
    contracts_dir = repo_dir / "config" / "contracts"
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_evolution.py"

    repo_dir.mkdir()
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.name", "Codex"], repo_dir)
    _run_git(["config", "user.email", "codex@example.com"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(_field("order_id", required=True)),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "base"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(
            _field("order_id", required=True),
            _field("discount_amount", "float", required=False),
        ),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "safe change"], repo_dir)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script_path),
            "--contracts-dir",
            "config/contracts",
            "--base-ref",
            "HEAD~1",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0


def test_schema_check_script_exits_one_for_breaking_change_without_version_bump(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo-breaking"
    contracts_dir = repo_dir / "config" / "contracts"
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_evolution.py"

    repo_dir.mkdir()
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.name", "Codex"], repo_dir)
    _run_git(["config", "user.email", "codex@example.com"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(
            _field("order_id", required=True),
            _field("status", required=True),
        ),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "base"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(_field("order_id", required=True)),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "breaking change"], repo_dir)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script_path),
            "--contracts-dir",
            "config/contracts",
            "--base-ref",
            "HEAD~1",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1


def test_schema_check_script_accepts_breaking_change_in_new_version_file(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo-version-bump"
    contracts_dir = repo_dir / "config" / "contracts"
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_evolution.py"

    repo_dir.mkdir()
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.name", "Codex"], repo_dir)
    _run_git(["config", "user.email", "codex@example.com"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(
            _field("order_id", required=True),
            _field("status", required=True),
        ),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "base"], repo_dir)

    _write_contract(
        contracts_dir / "order.v2.yaml",
        _schema(
            _field("order_id", required=True),
            version="2",
        ),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "breaking change with version bump"], repo_dir)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script_path),
            "--contracts-dir",
            "config/contracts",
            "--base-ref",
            "HEAD~1",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0


def test_schema_check_script_treats_missing_base_ref_as_first_commit(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo-first-commit"
    contracts_dir = repo_dir / "config" / "contracts"
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_evolution.py"

    repo_dir.mkdir()
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.name", "Codex"], repo_dir)
    _run_git(["config", "user.email", "codex@example.com"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(_field("order_id", required=True)),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "first commit"], repo_dir)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script_path),
            "--contracts-dir",
            "config/contracts",
            "--base-ref",
            "HEAD~1",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Schema evolution check passed." in completed.stdout


def test_schema_check_script_handles_first_commit_without_head_tilde_one(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo-first-commit"
    contracts_dir = repo_dir / "config" / "contracts"
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_evolution.py"

    repo_dir.mkdir()
    _run_git(["init"], repo_dir)
    _run_git(["config", "user.name", "Codex"], repo_dir)
    _run_git(["config", "user.email", "codex@example.com"], repo_dir)

    _write_contract(
        contracts_dir / "order.v1.yaml",
        _schema(
            _field("order_id", required=True),
            _field("status", required=True),
        ),
    )
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "initial contracts"], repo_dir)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script_path),
            "--contracts-dir",
            "config/contracts",
            "--base-ref",
            "HEAD~1",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Schema evolution check passed." in completed.stdout
