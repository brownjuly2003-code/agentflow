from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_staging_helm_rollout_is_atomic_and_diagnosable() -> None:
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")

    helm_upgrade_start = script.index('helm upgrade --install "$RELEASE_NAME"')
    helm_upgrade_end = script.index('echo "==> Enabling host loopback relay', helm_upgrade_start)
    helm_upgrade_block = script[helm_upgrade_start:helm_upgrade_end]

    assert "--atomic" in helm_upgrade_block
    assert 'helm history "$RELEASE_NAME" --namespace "$NAMESPACE"' in script


def test_staging_script_preflights_required_cluster_tools() -> None:
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")

    preflight_start = script.index("for cmd in")
    preflight_end = script.index('cd "$ROOT_DIR"', preflight_start)
    preflight_block = script[preflight_start:preflight_end]
    first_cluster_command = min(
        script.index("docker run"),
        script.index("kind get clusters"),
        script.index("helm history"),
        script.index("kubectl get"),
    )

    for command in ("bash", "curl", "docker", "helm", "kind", "kubectl"):
        assert command in preflight_block

    assert 'echo "Missing required command: $cmd" >&2' in preflight_block
    assert preflight_start < first_cluster_command


def test_staging_requires_promotion_values_before_cluster_mutation() -> None:
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")

    promotion_check = script.index('if [[ -z "$PROMOTION_VALUES_FILE" ]]')
    first_cluster_mutation = min(
        script.index("docker run"),
        script.index("kind create cluster"),
        script.index("kubectl create namespace"),
        script.index("helm upgrade --install"),
    )

    assert (
        "promotion values file is required"
        in script[promotion_check:first_cluster_mutation].lower()
    )
    assert promotion_check < first_cluster_mutation


def test_staging_promotes_without_building_or_loading_an_api_image() -> None:
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")

    assert "docker build" not in script
    assert "kind load" not in script
    assert 'PROMOTION_VALUES_FILE="${PROMOTION_VALUES_FILE:-}"' in script
    helm_upgrade_start = script.index('helm upgrade --install "$RELEASE_NAME"')
    helm_upgrade_end = script.index('echo "==> Enabling host loopback relay', helm_upgrade_start)
    helm_upgrade_block = script[helm_upgrade_start:helm_upgrade_end]
    assert '-f "$PROMOTION_VALUES_FILE"' in helm_upgrade_block


def test_staging_script_does_not_live_patch_api_command_or_args() -> None:
    """Host-loopback command/args must live in Helm desired state.

    A live JSON patch of command/args is clobbered on the next helm upgrade
    (hardcoded template command returns, orphaned args remain) and the new
    API replica fails with uvicorn 'unexpected extra argument'.
    """
    script = (PROJECT_ROOT / "scripts" / "k8s_staging_up.sh").read_text(encoding="utf-8")

    assert "kubectl set env" in script
    # kubectl patch must be its own command line after the progress echo;
    # a missing LF turns it into an echo argument (bash -n still passes).
    assert (
        'echo "==> Patching service to fixed NodePort..."\nkubectl patch service "$RELEASE_NAME" \\'
    ) in script
    assert "/spec/template/spec/containers/0/command" not in script
    assert "/spec/template/spec/containers/0/args" not in script
    assert "host_loopback_proxy.py" not in script.split("kubectl set env", 1)[1]
