from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FOUNDATION_ROOT = PROJECT_ROOT / "scripts" / "golden_soak"
PACK_ROOT = FOUNDATION_ROOT / "pack"
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.soak.yml"

EXPECTED_PACK = {
    "baseline-job.yaml": (4294, "a1ff62f52b4a8904c0629e691cf0081b4dbe9439a0cb9be89462ff7cfc1f97bf"),
    "baseline.py": (8522, "ea6db1bf37094d945f4346ee6f135434074827231e34de80a0be3252a4fa8280"),
    "observer.py": (24059, "3c2de4406b57b23a7b7ea3743a63fcd2004f35f9db753dd7efe330269de6f5a9"),
    "producer.py": (16460, "192a3dee4d6a232bb22ca7590acf4457a0dbfb48edafc4e7fca2f7c2d282f781"),
    "soak-observer-job.yaml": (
        4749,
        "25fad87807d92f6d78d8cfd705ee93ba0182477f42173b2e7b4bab38d1ec2951",
    ),
    "soak-producer-job.yaml": (
        3780,
        "61db1166b7dc4d12c0579bfa7321226d3e87b962158f99cfabf0b1346ab9aec7",
    ),
    "soak-verify-job.yaml": (
        5715,
        "0948256270ef094490d9c27e1165bad3aaf9f08d4cc0ae2b9f476788a031de4f",
    ),
    "verify.py": (54603, "9af870fa3a58ed4b7d2ec4118b1ae2c28868c97825556dc6651efd0f9972b8a7"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_tracked_source_pack_matches_the_recorded_identity_byte_for_byte() -> None:
    manifest = json.loads((FOUNDATION_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))

    assert manifest["source_identity"] == "20260819-07"
    assert manifest["contract_status"] == "source-reference-only"
    assert {path.name for path in PACK_ROOT.iterdir() if path.is_file()} == set(EXPECTED_PACK)
    assert set(manifest["files"]) == {f"pack/{name}" for name in EXPECTED_PACK}

    for name, (expected_bytes, expected_sha) in EXPECTED_PACK.items():
        path = PACK_ROOT / name
        entry = manifest["files"][f"pack/{name}"]
        assert path.stat().st_size == expected_bytes
        assert _sha256(path) == expected_sha
        assert entry == {"bytes": expected_bytes, "sha256": expected_sha}


def test_foundation_readme_keeps_gate_claims_fail_closed() -> None:
    text = (FOUNDATION_ROOT / "README.md").read_text(encoding="utf-8").lower()

    assert "separate capacity-independent" in text
    assert "does not close" in text
    assert "cannot emit a soak pass" in text
    assert "workflow" in text


def test_soak_overlay_contains_only_the_authorized_foundation_services() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    compose = yaml.safe_load(text)

    assert "TODO" not in text
    assert "DRAFT" not in text
    assert set(compose["services"]) == {
        "agentflow-api",
        "clickhouse",
        "flink-job-runner",
        "flink-jobmanager",
        "flink-taskmanager",
        "iceberg-init",
        "iceberg-rest",
        "kafka",
        "lake-materializer",
        "serving-bridge",
        "serving-init",
        "soak-topics-init",
    }
    assert {"redis", "postgres", "prometheus", "grafana"}.isdisjoint(compose["services"])
    assert set(compose["volumes"]) == {"soak-api-data"}


def test_soak_overlay_aligns_flink_policy_and_uses_one_taskmanager() -> None:
    services = _compose()["services"]
    expected = {
        "FLINK_CHECKPOINT_INTERVAL_MS": "10000",
        "FLINK_CHECKPOINT_MIN_PAUSE_MS": "10000",
        "FLINK_RESTART_MAX_FAILURES_PER_INTERVAL": "3",
        "FLINK_RESTART_FAILURE_RATE_INTERVAL_MS": "300000",
        "FLINK_RESTART_DELAY_MS": "10000",
        "AGENTFLOW_FLINK_GROUP_ID": "agentflow-ci-soak-stream",
        "AGENTFLOW_KAFKA_STARTUP_MODE": "earliest-offset",
        "FLINK_PARALLELISM": "2",
        "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
    }
    for name in ("flink-jobmanager", "flink-taskmanager", "flink-job-runner"):
        environment = services[name]["environment"]
        assert {key: environment[key] for key in expected} == expected

    assert services["flink-taskmanager"]["deploy"]["replicas"] == 1
    runner_dependencies = services["flink-job-runner"]["depends_on"]
    assert runner_dependencies["soak-topics-init"] == {
        "condition": "service_completed_successfully"
    }
    topics_command = "\n".join(services["soak-topics-init"]["command"])
    assert "orders.status" in topics_command


def test_soak_overlay_initializes_iceberg_before_the_lake_consumer() -> None:
    services = _compose()["services"]
    init = services["iceberg-init"]

    assert init["depends_on"]["iceberg-rest"] == {"condition": "service_started"}
    assert init["depends_on"]["minio-init"] == {"condition": "service_completed_successfully"}
    command = "\n".join(init["command"])
    assert "http://iceberg-rest:8181/v1/config" in command
    assert "/app/scripts/init_iceberg.py" in command
    assert services["lake-materializer"]["depends_on"]["iceberg-init"] == {
        "condition": "service_completed_successfully"
    }


def test_soak_overlay_wires_consumer_groups_and_ready_api() -> None:
    services = _compose()["services"]

    assert services["lake-materializer"]["environment"]["AGENTFLOW_LAKE_GROUP_ID"] == (
        "agentflow-ci-soak-lake"
    )
    assert services["serving-bridge"]["environment"]["AGENTFLOW_BRIDGE_GROUP_ID"] == (
        "agentflow-ci-soak-serving"
    )
    api = services["agentflow-api"]
    assert api["environment"]["AGENTFLOW_DEMO_MODE"] == "true"
    assert "/health/ready" in " ".join(str(value) for value in api["healthcheck"]["test"])


def test_soak_overlay_gives_jobmanager_healthcheck_startup_grace_only() -> None:
    services = _compose()["services"]

    assert services["flink-jobmanager"]["healthcheck"] == {"start_period": "90s"}
