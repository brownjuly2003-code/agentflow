"""Shape tests for the production CDC capture evidence channel (item 19).

The workflow must stay dispatch-only (it talks to the real production Neon
database), must pass connection material only through Actions secrets into a
FileConfigProvider properties file (never inline in connector JSON), and the
capture script must carry an unconditional teardown trap so the replication
slot can never be left behind to retain WAL on the production project.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "cdc-production-capture.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _script_text() -> str:
    path = PROJECT_ROOT / "scripts" / "capture_production_cdc.sh"
    return path.read_text(encoding="utf-8")


def _on_section(workflow: dict) -> dict:
    # An unquoted `on:` key parses as the YAML boolean True; accept both.
    return workflow.get("on", workflow.get(True))


def test_cdc_capture_is_dispatch_only():
    on = _on_section(_load_workflow())

    assert "workflow_dispatch" in on
    assert "pull_request" not in on
    assert "push" not in on
    assert "schedule" not in on


def test_cdc_capture_reads_connection_from_secrets():
    workflow_text = (
        PROJECT_ROOT / ".github" / "workflows" / "cdc-production-capture.yml"
    ).read_text(encoding="utf-8")

    for secret in (
        "CDC_NEON_HOSTNAME",
        "CDC_NEON_USER",
        "CDC_NEON_PASSWORD",
        "CDC_NEON_DBNAME",
    ):
        assert f"secrets.{secret}" in workflow_text


def test_cdc_capture_script_uses_file_config_provider_for_credentials():
    script = _script_text()

    assert "${file:/opt/connect/secrets/neon.properties:password}" in script
    assert "database.sslmode" in script
    assert '"require"' in script


def test_cdc_capture_script_has_unconditional_teardown_trap():
    script = _script_text()

    assert "trap teardown EXIT" in script
    assert "pg_drop_replication_slot" in script
    assert "DROP PUBLICATION IF EXISTS" in script


def test_cdc_capture_uploads_evidence_even_on_failure():
    job = _load_workflow()["jobs"]["cdc-production-capture"]

    upload_steps = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert upload_steps
    assert upload_steps[0].get("if") == "always()"
