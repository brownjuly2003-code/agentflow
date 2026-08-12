"""Static contract for the Flink job image Kafka connector acquisition.

Pins integrity-checked multi-endpoint download with a BuildKit cache so Maven
Central rate-limits cannot single-point the image build. Pure text inspection —
no Docker, no network.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = PROJECT_ROOT / "src" / "processing" / "flink_jobs" / "Dockerfile"

CONNECTOR_VERSION = "5.0.0-2.2"
# Shell-form RUN is /bin/sh: runtime locals use normal POSIX ${var}/$1/$(...).
INSTALL_VIA_VAR = 'install_jar="/opt/flink/lib/${connector_jar}"'
LEGACY_DIRECT_INSTALL = (
    '"/opt/flink/lib/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar"'
)
# Official Maven Central SHA-1 sidecar / X-Checksum-Sha1 for this coordinate.
PINNED_SHA1 = "7bf2ded1144cb8aece05adcaccbc81b2ac3ef339"
PINNED_BYTES = "10666527"
MAVEN_CENTRAL_ROOT = "https://repo.maven.apache.org/maven2"
APACHE_RELEASES_ROOT = "https://repository.apache.org/content/repositories/releases"
CACHE_MOUNT_ID = f"flink-sql-connector-kafka-{CONNECTOR_VERSION}"
CACHE_MOUNT_TARGET = "/var/cache/flink-connectors"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_connector_version_and_install_path_remain_pinned() -> None:
    text = _dockerfile()

    assert f"ARG PYFLINK_KAFKA_JAR_VERSION={CONNECTOR_VERSION}" in text
    assert INSTALL_VIA_VAR in text
    assert "flink-sql-connector-kafka" in text


def test_connector_integrity_is_hardcoded_and_verified() -> None:
    text = _dockerfile()

    assert f"ARG PYFLINK_KAFKA_JAR_SHA1={PINNED_SHA1}" in text
    assert f"ARG PYFLINK_KAFKA_JAR_BYTES={PINNED_BYTES}" in text
    assert "sha1sum" in text
    assert "verify_jar" in text


def test_buildkit_cache_mount_has_stable_connector_identity() -> None:
    text = _dockerfile()

    assert "--mount=type=cache" in text
    assert f"id={CACHE_MOUNT_ID}" in text
    assert f"target={CACHE_MOUNT_TARGET}" in text


def test_both_trusted_endpoint_roots_are_present() -> None:
    text = _dockerfile()

    assert MAVEN_CENTRAL_ROOT in text
    assert APACHE_RELEASES_ROOT in text


def test_valid_cache_hit_bypasses_endpoint_loop() -> None:
    """Cache verification gates the download loop (if-not-valid → fetch)."""
    text = _dockerfile()

    # Control-flow must only enter network acquisition when cache verify fails.
    assert "if ! verify_jar" in text
    assert "for base in" in text
    # Endpoint loop lives inside the cache-miss branch.
    miss_branch_start = text.index("if ! verify_jar")
    miss_branch = text[miss_branch_start:]
    assert "for base in" in miss_branch
    assert MAVEN_CENTRAL_ROOT in miss_branch
    assert APACHE_RELEASES_ROOT in miss_branch


def test_runtime_shell_refs_are_not_doubled_dollar() -> None:
    """Shell-form RUN is /bin/sh: $$ is the shell PID, not Docker escaping."""
    text = _dockerfile()

    runtime_markers = (
        "$${connector_jar}",
        "$${cache_jar}",
        "$${install_jar}",
        "$${coord}",
        "$${tmp_jar}",
        "$${acquired}",
        "$${base}",
        "$$(mktemp",
        "$$(stat",
        '"$$1"',
        " $$1 ",
        " $$1|",
        " $$1;",
    )
    for marker in runtime_markers:
        assert marker not in text, f"doubled-dollar runtime shell ref: {marker}"

    assert 'install_jar="/opt/flink/lib/${connector_jar}"' in text
    assert 'cache_jar="/var/cache/flink-connectors/${connector_jar}"' in text
    assert 'verify_jar "${cache_jar}"' in text
    assert 'verify_jar "${install_jar}"' in text
    assert 'test -f "$1"' in text
    assert '$(stat -c%s "$1")' in text


def test_temp_download_is_verified_before_cache_promotion() -> None:
    text = _dockerfile()

    assert "mktemp" in text
    assert "verify_jar" in text
    assert 'mv -f "${tmp_jar}" "${cache_jar}"' in text
    # Download target is the temp path, never the cache/install path directly.
    assert '-o "${tmp_jar}"' in text
    # Temp must live on the cache mount so mv to cache_jar is same-FS atomic.
    assert 'mktemp "${cache_jar}.tmp.XXXXXX"' in text
    tmp_assign = 'tmp_jar="$(mktemp "${cache_jar}.tmp.XXXXXX")"'
    assert tmp_assign in text
    # Template is derived from cache_jar (under the cache mount target).
    assert f'cache_jar="{CACHE_MOUNT_TARGET}/' in text
    tmp_pos = text.index(tmp_assign)
    mv_pos = text.index('mv -f "${tmp_jar}" "${cache_jar}"')
    assert tmp_pos < mv_pos


def test_cached_artifact_is_reverified_before_install() -> None:
    text = _dockerfile()

    # After the cache-miss fi, cache is re-verified then installed into /opt/flink/lib.
    install_cmd = 'install -m 0644 "${cache_jar}" "${install_jar}"'
    assert install_cmd in text
    assert 'verify_jar "${install_jar}"' in text
    # Gate + post-miss re-check both call verify_jar on the cache path.
    assert text.count('verify_jar "${cache_jar}"') >= 2
    # Order on the install path: re-verify cache → install → re-verify install.
    # Use the last cache verify (post-fi) so the if-gate match is not mistaken.
    reverify_cache = text.rindex('verify_jar "${cache_jar}"')
    install_pos = text.index(install_cmd)
    reverify_install = text.index('verify_jar "${install_jar}"')
    assert reverify_cache < install_pos < reverify_install


def test_runtime_jar_installed_with_deterministic_mode_0644() -> None:
    """mktemp/cp leave root-owned 0600 JARs unreadable by USER flink SPI load.

    The verified cache artifact must be installed to ${install_jar} with mode
    0644 before the final verify_jar on the installed path. Plain cp is
    forbidden: it preserves the cache source mode (often 0600 from mktemp).
    """
    text = _dockerfile()

    install_cmd = 'install -m 0644 "${cache_jar}" "${install_jar}"'
    assert install_cmd in text
    assert 'cp -f "${cache_jar}" "${install_jar}"' not in text
    # Do not widen the cached source or chmod the whole lib tree.
    assert 'chmod 0644 "${cache_jar}"' not in text
    assert "chmod -R" not in text

    reverify_cache = text.rindex('verify_jar "${cache_jar}"')
    install_pos = text.index(install_cmd)
    reverify_install = text.index('verify_jar "${install_jar}"')
    assert reverify_cache < install_pos < reverify_install


def test_old_single_direct_curl_to_lib_is_absent() -> None:
    text = _dockerfile()

    # Forbidden: single-endpoint curl writing straight into the runtime lib path.
    assert f"-o {LEGACY_DIRECT_INSTALL}" not in text
    assert '-o "/opt/flink/lib/flink-sql-connector-kafka-' not in text
    assert (
        f'curl -fsSL $CURL_GUARDS "{MAVEN_CENTRAL_ROOT}/org/apache/flink/'
        "flink-sql-connector-kafka/${PYFLINK_KAFKA_JAR_VERSION}/"
        'flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" '
        f"-o {LEGACY_DIRECT_INSTALL}"
    ) not in text
