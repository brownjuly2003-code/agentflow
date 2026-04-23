import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_contract_extra_installs_schemathesis():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    contract = pyproject["project"]["optional-dependencies"].get("contract")

    assert contract is not None
    assert any(dependency.startswith("schemathesis") for dependency in contract)


def test_contract_workflow_uses_contract_extra():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "contract.yml").read_text(
        encoding="utf-8"
    )

    assert 'pip install -e ".[dev,cloud,contract]"' in workflow
    assert "pip install schemathesis" not in workflow
