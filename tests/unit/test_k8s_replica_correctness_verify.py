"""Static contract for scripts/k8s_replica_correctness_verify.sh.

Live execution needs a scale-profile kind stand (Mac). These checks pin the
automation surface so Checks 1–4 cannot silently regress to recipe-only docs.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "k8s_replica_correctness_verify.sh"


def test_replica_correctness_script_automates_checks_1_through_4() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert SCRIPT.exists()
    assert "set -Eeuo pipefail" in text

    # Check markers and key assertions for each phase-3 topology check.
    assert "[Check 1]" in text
    assert "AGENTFLOW_CONTROLPLANE_STORE" in text
    assert "status.phase=Running" in text  # skip Completed provision Job pods

    assert "[Check 2]" in text
    assert "/v1/webhooks" in text

    assert "[Check 3]" in text
    assert "pipeline_events" in text
    assert "delivery_id" in text
    # POST target must accept POST with 2xx (example.com → 405 confuses exactly-one).
    assert "httpbin.org/post" in text or "WEBHOOK_URL" in text
    assert "example.com/agentflow-replica-verify" not in text.split("WEBHOOK_URL=")[1].splitlines()[0]

    assert "[Check 4]" in text
    assert "/v1/alerts" in text
    assert "alert.triggered" in text
    assert "claim_alert_tick" in text or "single-flight" in text.lower()

    # Cleanup must cover both webhook and alert created by the script.
    assert '"/v1/alerts/$alert_id"' in text or "/v1/alerts/$alert_id" in text
