import io
import tarfile

from scripts.check_release_artifacts import find_forbidden_members


def test_release_artifact_checker_rejects_secret_paths(tmp_path):
    artifact = tmp_path / "agentflow_runtime-1.1.0.tar.gz"
    _write_targz(
        artifact,
        [
            "agentflow_runtime-1.1.0/src/serving/__init__.py",
            "agentflow_runtime-1.1.0/config/webhooks.yaml",
            "agentflow_runtime-1.1.0/docker/kafka-connect/secrets/mysql.properties",
        ],
    )

    violations = find_forbidden_members(artifact)

    assert "agentflow_runtime-1.1.0/config/webhooks.yaml" in violations
    assert "agentflow_runtime-1.1.0/docker/kafka-connect/secrets/mysql.properties" in violations


def test_release_artifact_checker_accepts_runtime_sdist_allowlist(tmp_path):
    artifact = tmp_path / "agentflow_runtime-1.1.0.tar.gz"
    _write_targz(
        artifact,
        [
            "agentflow_runtime-1.1.0/src/serving/__init__.py",
            "agentflow_runtime-1.1.0/README.md",
            "agentflow_runtime-1.1.0/LICENSE",
            "agentflow_runtime-1.1.0/CHANGELOG.md",
            "agentflow_runtime-1.1.0/pyproject.toml",
        ],
    )

    assert find_forbidden_members(artifact) == []


def _write_targz(path, names):
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            data = b"placeholder\n"
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
