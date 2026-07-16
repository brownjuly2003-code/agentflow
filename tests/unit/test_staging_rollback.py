from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_staging_helm_rollout_is_atomic_and_diagnosable() -> None:
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")

    helm_upgrade_start = script.index('helm upgrade --install "$RELEASE_NAME"')
    helm_upgrade_end = script.index('echo "==> Enabling host loopback relay', helm_upgrade_start)
    helm_upgrade_block = script[helm_upgrade_start:helm_upgrade_end]

    assert "--atomic" in helm_upgrade_block
    assert 'helm history "$RELEASE_NAME" --namespace "$NAMESPACE"' in script


def test_staging_image_installs_postgres_extra_and_pyiceberg() -> None:
    """E4 kind stand (2026-07-16): API CrashLoop without pyiceberg because
    HealthCollector imports it at module load. Staging inline Dockerfile must
    keep both the postgres extra and an explicit pyiceberg install.
    """
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")
    assert 'pip install --no-cache-dir -e ".[postgres]"' in script
    assert "pip install --no-cache-dir pyiceberg" in script
