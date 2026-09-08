"""Contract: Dockerfile.api final stage upgrades OpenSSL for CVE-2026-14456 (AG-06 / F-03).

Docker is not available on the Windows development host, so these checks read
the Dockerfile text rather than building an image. Image rebuild + Trivy proof
is the CI `trivy` job after the orchestrator pushes.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile.api"

OPENSSL_PACKAGES = ("libssl3t64", "openssl", "openssl-provider-legacy")
UTIL_LINUX_PACKAGES = (
    "bsdutils",
    "libblkid1",
    "libmount1",
    "libsmartcols1",
    "libuuid1",
    "mount",
    "util-linux",
)


def _stages() -> tuple[str, str]:
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    from_splits = text.split("\nFROM ")
    assert len(from_splits) == 2, "Dockerfile.api must have exactly two FROM stages"
    builder = from_splits[0]
    final_stage = "FROM " + from_splits[1]
    return builder, final_stage


def _only_upgrade_packages(stage: str) -> list[str]:
    marker = "--only-upgrade"
    assert marker in stage, "final stage must contain an --only-upgrade install"
    after = stage.split(marker, maxsplit=1)[1]
    package_block, _sep, _rest = after.partition("&&")
    tokens = package_block.replace("\\", " ").split()
    return [token for token in tokens if token and not token.startswith("-")]


def test_dockerfile_api_has_one_only_upgrade_block_in_the_final_stage() -> None:
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    builder, final_stage = _stages()

    assert text.count("--only-upgrade") == 1
    assert "--only-upgrade" in final_stage
    assert "--only-upgrade" not in builder
    assert "--no-install-recommends --only-upgrade" in final_stage
    assert "apt-get clean" in final_stage
    assert "rm -rf /var/lib/apt/lists/*" in final_stage


def test_dockerfile_api_final_stage_upgrades_openssl_for_cve_2026_14456() -> None:
    _builder, final_stage = _stages()
    packages = _only_upgrade_packages(final_stage)

    assert "CVE-2026-14456" in final_stage
    assert "Audit AG-06" in final_stage
    for name in OPENSSL_PACKAGES:
        assert name in packages, f"{name} must be in the final-stage --only-upgrade list"
    for name in UTIL_LINUX_PACKAGES:
        assert name in packages, f"{name} must remain in the final-stage --only-upgrade list"


def test_dockerfile_api_builder_does_not_ship_openssl_into_the_final_image() -> None:
    builder, final_stage = _stages()

    copy_from_builder = [
        line.strip()
        for line in final_stage.splitlines()
        if line.strip().upper().startswith("COPY ") and "--from=builder" in line.lower()
    ]
    assert copy_from_builder == ["COPY --from=builder /tmp/dist /tmp/dist"]
    assert "python -m build --wheel" in builder
    # The shipped artifact is the project wheel under /tmp/dist. System OpenSSL
    # from the builder filesystem is not copied into the runtime image.
    assert all("libssl" not in line and "openssl" not in line.lower() for line in copy_from_builder)
