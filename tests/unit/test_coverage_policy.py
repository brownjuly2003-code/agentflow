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
