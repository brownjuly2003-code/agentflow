from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_ci_has_scoped_quality_validators_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run quality validators coverage gate"),
        None,
    )

    assert gate_step is not None
    assert "tests/unit/test_validators.py" in gate_step["run"]
    assert "--cov=src.quality.validators" in gate_step["run"]
    assert "--cov-fail-under=90" in gate_step["run"]


def test_ci_has_scoped_freshness_monitor_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run freshness monitor coverage gate"),
        None,
    )

    assert gate_step is not None
    assert "tests/unit/test_freshness_monitor.py" in gate_step["run"]
    assert "--cov=src.quality.monitors.freshness_monitor" in gate_step["run"]
    assert "--cov-fail-under=90" in gate_step["run"]


def test_ci_has_scoped_event_producer_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run event producer coverage gate"),
        None,
    )

    assert gate_step is not None
    assert "tests/unit/test_event_producer.py" in gate_step["run"]
    assert "--cov=src.ingestion.producers.event_producer" in gate_step["run"]
    assert "--cov-fail-under=90" in gate_step["run"]


def test_ci_has_scoped_sql_guard_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run SQL guard coverage gate"),
        None,
    )

    assert gate_step is not None
    assert "tests/unit/test_sql_guard.py" in gate_step["run"]
    assert "--cov=src.serving.semantic_layer.sql_guard" in gate_step["run"]
    assert "--cov-fail-under=90" in gate_step["run"]


def test_ci_has_scoped_pii_masking_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run PII masking coverage gate"),
        None,
    )

    assert gate_step is not None
    assert "tests/unit/test_masking.py" in gate_step["run"]
    assert "--cov=src.serving.masking" in gate_step["run"]
    assert "--cov-fail-under=90" in gate_step["run"]


def test_ci_has_scoped_rate_limiter_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run rate limiter coverage gate"),
        None,
    )

    assert gate_step is not None
    assert "tests/unit/test_rate_limiter.py" in gate_step["run"]
    assert "--cov=src.serving.api.rate_limiter" in gate_step["run"]
    assert "--cov-fail-under=90" in gate_step["run"]


def test_ci_has_scoped_auth_manager_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run auth manager coverage gate"),
        None,
    )

    assert gate_step is not None
    # The auth manager pulls in duckdb, and pytest-cov's source instrumentation
    # of a duckdb-importing module trips duckdb's lazy `_duckdb._sqltypes`
    # import at collection time (local + CI), so this gate uses `coverage run`
    # + `coverage report --include` instead of `pytest --cov=<module>`.
    assert "tests/unit/test_auth_manager_pure_logic.py" in gate_step["run"]
    assert "coverage run -m pytest" in gate_step["run"]
    assert "*/serving/api/auth/manager.py" in gate_step["run"]
    assert "--fail-under=90" in gate_step["run"]


def test_ci_has_scoped_key_rotation_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run key rotation coverage gate"),
        None,
    )

    assert gate_step is not None
    # key_rotation imports duckdb, so the gate uses coverage run + report
    # --include rather than pytest --cov (same duckdb-under-cov constraint as
    # the auth manager gate).
    assert "tests/unit/test_key_rotation.py" in gate_step["run"]
    assert "coverage run -m pytest" in gate_step["run"]
    assert "*/serving/api/auth/key_rotation.py" in gate_step["run"]
    assert "--fail-under=90" in gate_step["run"]


def test_ci_has_scoped_outbox_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run outbox coverage gate"),
        None,
    )

    assert gate_step is not None
    # outbox imports duckdb, so the gate uses coverage run + report --include
    # rather than pytest --cov (same duckdb-under-cov constraint as the auth gates).
    assert "tests/unit/test_outbox_processor.py" in gate_step["run"]
    assert "coverage run -m pytest" in gate_step["run"]
    assert "*/processing/outbox.py" in gate_step["run"]
    assert "--fail-under=90" in gate_step["run"]


def test_ci_has_scoped_query_package_coverage_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]

    gate_step = next(
        (step for step in steps if step.get("name") == "Run query package coverage gate"),
        None,
    )

    assert gate_step is not None
    # The query engine imports duckdb, so the gate uses coverage run + report
    # --include rather than pytest --cov (same duckdb-under-cov constraint as
    # the auth/outbox gates). The gate spans the whole query package: the old
    # single-file query_engine.py is a re-export shim.
    assert "tests/unit/test_query_package_logic.py" in gate_step["run"]
    assert "coverage run" in gate_step["run"]
    assert "*/serving/semantic_layer/query/*" in gate_step["run"]
    assert "--fail-under=90" in gate_step["run"]
