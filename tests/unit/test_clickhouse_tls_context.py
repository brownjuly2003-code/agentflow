"""P2-3: the ClickHouse client's TLS trust is explicit and fails loudly.

`secure=true` has always meant "verify against the system store"; these
tests pin the private-CA path added by audit P2-3 — a `ca_cert` bundle
REPLACES the system store (an unrelated public CA must not be able to
impersonate the serving store) and a bad bundle path refuses to
construct instead of silently falling back to defaults.
"""

from __future__ import annotations

import ssl
from pathlib import Path

import pytest

from src.serving.backends import load_serving_backend_config
from src.serving.backends.clickhouse_backend import ClickHouseBackend

TEST_CA = Path(__file__).resolve().parents[1] / "fixtures" / "tls" / "test-ca.pem"


def _backend(**kwargs) -> ClickHouseBackend:
    return ClickHouseBackend(
        host="ch.example.internal",
        port=8443,
        user="agentflow",
        password="secret",
        database="agentflow",
        **kwargs,
    )


def test_plaintext_backend_builds_no_tls_context() -> None:
    assert _backend(secure=False)._ssl_context is None


def test_secure_backend_verifies_hostname_against_system_store() -> None:
    context = _backend(secure=True)._ssl_context

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_private_ca_replaces_the_system_store() -> None:
    context = _backend(secure=True, ca_cert=str(TEST_CA))._ssl_context

    assert isinstance(context, ssl.SSLContext)
    # Exactly the one fixture CA: a server cert signed by any public CA
    # must NOT verify against this context.
    assert context.cert_store_stats()["x509_ca"] == 1
    assert context.check_hostname is True


def test_missing_ca_bundle_refuses_to_construct() -> None:
    with pytest.raises(FileNotFoundError):
        _backend(secure=True, ca_cert=str(TEST_CA.with_name("no-such-ca.pem")))


def test_ca_cert_flows_from_env_and_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serving_yaml = tmp_path / "serving.yaml"
    serving_yaml.write_text(
        "backend: clickhouse\nclickhouse:\n  host: ch.example.internal\n"
        "  secure: true\n  ca_cert: /etc/agentflow/tls/yaml-ca.pem\n",
        encoding="utf-8",
    )
    for var in ("CLICKHOUSE_CA_CERT", "CLICKHOUSE_SECURE"):
        monkeypatch.delenv(var, raising=False)

    from_yaml = load_serving_backend_config(serving_yaml)["clickhouse"]
    assert from_yaml["ca_cert"] == "/etc/agentflow/tls/yaml-ca.pem"
    assert from_yaml["secure"] is True

    monkeypatch.setenv("CLICKHOUSE_CA_CERT", "/run/secrets/env-ca.pem")
    assert (
        load_serving_backend_config(serving_yaml)["clickhouse"]["ca_cert"]
        == "/run/secrets/env-ca.pem"
    )

    # Unset everywhere -> None, so the backend falls back to the system store.
    monkeypatch.delenv("CLICKHOUSE_CA_CERT")
    plain_yaml = tmp_path / "plain.yaml"
    plain_yaml.write_text("backend: clickhouse\nclickhouse: {}\n", encoding="utf-8")
    assert load_serving_backend_config(plain_yaml)["clickhouse"]["ca_cert"] is None
