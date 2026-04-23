from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.processing.iceberg_sink import IcebergSink


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
