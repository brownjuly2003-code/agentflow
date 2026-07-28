"""Contract tests for the Flink Operator 1.15 CRD compatibility patch."""

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "patch_flink_operator_1_15_crd.py"
UPSTREAM_1_15_ENUM = [
    "v1_13",
    "v1_14",
    "v1_15",
    "v1_16",
    "v1_17",
    "v1_18",
    "v1_19",
    "v1_20",
    "v2_0",
    "v2_1",
    "v2_2",
]


def _load_script():
    assert SCRIPT_PATH.exists()
    spec = importlib.util.spec_from_file_location("patch_flink_operator_1_15_crd", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crd(flink_versions: list[str]) -> dict:
    return {
        "spec": {
            "versions": [
                {
                    "name": "v1beta1",
                    "schema": {
                        "openAPIV3Schema": {
                            "properties": {
                                "spec": {
                                    "properties": {
                                        "flinkVersion": {
                                            "enum": flink_versions,
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            ]
        }
    }


def test_build_patch_adds_v2_3_only_to_the_exact_operator_1_15_schema():
    module = _load_script()

    patch = module.build_flinkdeployment_crd_patch(_crd(UPSTREAM_1_15_ENUM.copy()))

    enum_path = (
        "/spec/versions/0/schema/openAPIV3Schema/properties/spec/properties/flinkVersion/enum"
    )
    assert patch == [
        {"op": "test", "path": "/spec/versions/0/name", "value": "v1beta1"},
        {"op": "test", "path": enum_path, "value": UPSTREAM_1_15_ENUM},
        {"op": "add", "path": f"{enum_path}/-", "value": "v2_3"},
    ]


def test_build_patch_is_idempotent_after_v2_3_is_present():
    module = _load_script()

    assert module.build_flinkdeployment_crd_patch(_crd([*UPSTREAM_1_15_ENUM, "v2_3"])) == []


def test_build_patch_refuses_an_unknown_flink_version_enum():
    module = _load_script()

    with pytest.raises(ValueError, match="unexpected FlinkVersion enum"):
        module.build_flinkdeployment_crd_patch(_crd([*UPSTREAM_1_15_ENUM, "v9_9"]))


def test_patch_command_applies_the_guarded_patch_and_verifies_it(monkeypatch):
    module = _load_script()
    payloads = iter(
        [
            _crd(UPSTREAM_1_15_ENUM.copy()),
            _crd([*UPSTREAM_1_15_ENUM, "v2_3"]),
        ]
    )
    commands = []
    monkeypatch.setattr(module, "_load_crd", lambda _kubectl: next(payloads))
    monkeypatch.setattr(
        module,
        "_run_kubectl",
        lambda _kubectl, arguments: commands.append(arguments) or "",
    )

    result = module.patch_flinkdeployment_crd("kubectl")

    assert result["status"] == "patched"
    assert commands[0][:5] == [
        "patch",
        "crd",
        "flinkdeployments.flink.apache.org",
        "--type=json",
        "-p",
    ]
    assert json.loads(commands[0][5])[-1]["value"] == "v2_3"


def test_patch_command_does_not_mutate_an_already_compatible_crd(monkeypatch):
    module = _load_script()
    monkeypatch.setattr(
        module,
        "_load_crd",
        lambda _kubectl: _crd([*UPSTREAM_1_15_ENUM, "v2_3"]),
    )

    result = module.patch_flinkdeployment_crd("kubectl")

    assert result["status"] == "already-compatible"
