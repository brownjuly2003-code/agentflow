from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.processing.iceberg_sink import IcebergSink, _expand_env


def test_rest_catalog_uses_warehouse_identifier_without_local_mkdir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config" / "iceberg.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "iceberg": {
                    "catalog_type": "rest",
                    "catalog_uri": "http://localhost:8181",
                    "warehouse": "/warehouse",
                    "namespace": "agentflow",
                    "tables": [],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    captured: dict[str, object] = {}
    mkdir_calls: list[Path] = []

    class FakeCatalog:
        def create_namespace_if_not_exists(self, namespace: str) -> None:
            captured["namespace"] = namespace

    def fake_load_catalog(name: str, **kwargs: str) -> FakeCatalog:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return FakeCatalog()

    def fake_mkdir(self: Path, parents: bool = False, exist_ok: bool = False) -> None:
        mkdir_calls.append(self)

    monkeypatch.setattr("src.processing.iceberg_sink.load_catalog", fake_load_catalog)
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    IcebergSink(config_path=config_path)

    assert captured["name"] == "agentflow"
    assert captured["namespace"] == "agentflow"
    assert captured["kwargs"] == {
        "type": "rest",
        "uri": "http://localhost:8181",
        "warehouse": "/warehouse",
    }
    assert mkdir_calls == []


def test_sql_catalog_resolves_relative_warehouse_against_config_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config" / "iceberg.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "iceberg": {
                    "catalog_type": "sql",
                    "catalog_uri": "sqlite:///catalog.db",
                    "warehouse": "../warehouse",
                    "namespace": "agentflow",
                    "tables": [],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    captured: dict[str, object] = {}

    class FakeCatalog:
        def create_namespace_if_not_exists(self, namespace: str) -> None:
            captured["namespace"] = namespace

    def fake_load_catalog(name: str, **kwargs: str) -> FakeCatalog:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return FakeCatalog()

    monkeypatch.setattr("src.processing.iceberg_sink.load_catalog", fake_load_catalog)

    IcebergSink(config_path=config_path)

    warehouse_path = (tmp_path / "warehouse").resolve().as_posix()
    if os.name == "nt":
        warehouse_path = f"file:{warehouse_path}"

    assert captured["name"] == "agentflow"
    assert captured["namespace"] == "agentflow"
    assert captured["kwargs"] == {
        "type": "sql",
        "uri": f"sqlite:///{(tmp_path / 'config' / 'catalog.db').resolve().as_posix()}",
        "warehouse": warehouse_path,
    }
    assert (tmp_path / "warehouse").is_dir()


def test_expand_env_resolves_default_env_and_plain_values(monkeypatch) -> None:
    monkeypatch.delenv("ICEBERG_TEST_VAR", raising=False)
    assert _expand_env("${ICEBERG_TEST_VAR:-fallback}") == "fallback"
    monkeypatch.setenv("ICEBERG_TEST_VAR", "from-env")
    assert _expand_env("${ICEBERG_TEST_VAR:-fallback}") == "from-env"
    assert _expand_env("${ICEBERG_TEST_VAR}") == "from-env"
    # No reference and non-strings pass through untouched.
    assert _expand_env("s3://agentflow-lake/warehouse") == "s3://agentflow-lake/warehouse"
    assert _expand_env(True) is True


def test_s3_rest_catalog_expands_env_credentials_without_local_mkdir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config" / "iceberg.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "iceberg": {
                    "catalog_type": "rest",
                    "catalog_uri": "${AGENTFLOW_ICEBERG_URI:-http://localhost:8181}",
                    "warehouse": "${AGENTFLOW_ICEBERG_WAREHOUSE:-s3://agentflow-lake/warehouse}",
                    "namespace": "agentflow",
                    "catalog_properties": {
                        "s3.endpoint": "${AGENTFLOW_S3_ENDPOINT:-http://localhost:9000}",
                        "s3.access-key-id": "${AGENTFLOW_S3_ACCESS_KEY:-minio}",
                        "s3.secret-access-key": "${AGENTFLOW_S3_SECRET_KEY:-minio123}",
                        "s3.region": "${AGENTFLOW_S3_REGION:-us-east-1}",
                    },
                    "tables": [],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    for name in (
        "AGENTFLOW_ICEBERG_URI",
        "AGENTFLOW_ICEBERG_WAREHOUSE",
        "AGENTFLOW_S3_ENDPOINT",
        "AGENTFLOW_S3_ACCESS_KEY",
        "AGENTFLOW_S3_SECRET_KEY",
        "AGENTFLOW_S3_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    # Production-style override is honoured.
    monkeypatch.setenv("AGENTFLOW_S3_ENDPOINT", "https://s3.example.com")

    captured: dict[str, object] = {}
    mkdir_calls: list[Path] = []

    class FakeCatalog:
        def create_namespace_if_not_exists(self, namespace: str) -> None:
            captured["namespace"] = namespace

    def fake_load_catalog(name: str, **kwargs: str) -> FakeCatalog:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return FakeCatalog()

    def fake_mkdir(self: Path, parents: bool = False, exist_ok: bool = False) -> None:
        mkdir_calls.append(self)

    monkeypatch.setattr("src.processing.iceberg_sink.load_catalog", fake_load_catalog)
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    IcebergSink(config_path=config_path)

    assert captured["kwargs"] == {
        "type": "rest",
        "uri": "http://localhost:8181",
        "warehouse": "s3://agentflow-lake/warehouse",
        "s3.endpoint": "https://s3.example.com",
        "s3.access-key-id": "minio",
        "s3.secret-access-key": "minio123",
        "s3.region": "us-east-1",
    }
    # An s3:// warehouse must never create a local directory.
    assert mkdir_calls == []
