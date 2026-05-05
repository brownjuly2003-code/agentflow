from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import bcrypt
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager, KeyCreateRequest, build_auth_middleware


class FrozenClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _hash_key(value: str, rounds: int = 4) -> str:
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def _write_api_keys(path: Path, key_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "key_hash": key_hash,
                        "name": "Order Agent",
                        "tenant": "acme",
                        "rate_limit_rpm": 5,
                        "allowed_entity_types": ["order"],
                        "created_at": "2026-04-10",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_security_config(
    path: Path,
    *,
    bcrypt_rounds: int = 4,
    max_failed_auth_per_ip_per_hour: int = 10,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "security": {
                    "key_hashing": "bcrypt",
                    "bcrypt_rounds": bcrypt_rounds,
                    "min_key_length": 32,
                    "max_failed_auth_per_ip_per_hour": max_failed_auth_per_ip_per_hour,
                    "sensitive_headers_to_redact": ["Authorization", "X-API-Key"],
                    "request_size_limit_bytes": 1_048_576,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


def _build_app(api_keys_path: Path, security_config_path: Path, db_path: Path) -> FastAPI:
    from src.serving.api.security import build_security_headers_middleware

    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        admin_key="admin-secret",
        security_config_path=security_config_path,
    )
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())
    app.middleware("http")(build_security_headers_middleware())

    @app.get("/v1/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/v1/entity/{entity_type}/{entity_id}")
    async def get_entity(entity_type: str, entity_id: str):
        return {"entity_type": entity_type, "entity_id": entity_id}

    return app


@pytest.fixture
def security_config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "security.yaml"
    _write_security_config(path)
    return path


@pytest.fixture
def api_keys_path(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "api_keys.yaml"
    _write_api_keys(path, _hash_key("tenant-order-key"))
    return path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "usage.duckdb"


def test_authenticate_supports_bcrypt_hashes(
    api_keys_path: Path,
    security_config_path: Path,
    db_path: Path,
) -> None:
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
    )

    manager.load()
    tenant_key = manager.authenticate("tenant-order-key")

    assert tenant_key is not None
    assert tenant_key.name == "Order Agent"
    assert tenant_key.allowed_entity_types == ["order"]


def test_authenticate_legacy_plaintext_keys_uses_constant_time_compare(
    tmp_path: Path,
    security_config_path: Path,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "key": "tenant-order-key",
                        "name": "Legacy Agent",
                        "tenant": "acme",
                        "rate_limit_rpm": 5,
                        "allowed_entity_types": ["order"],
                        "created_at": "2026-04-10",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    from src.serving.api import auth as auth_module

    calls: list[tuple[str, str]] = []
    original_compare_digest = auth_module.secrets.compare_digest

    def recording_compare_digest(left: str, right: str) -> bool:
        calls.append((left, right))
        return original_compare_digest(left, right)

    monkeypatch.setattr(auth_module.secrets, "compare_digest", recording_compare_digest)

    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
    )
    manager.load()

    tenant_key = manager.authenticate("tenant-order-key")

    assert tenant_key is not None
    assert ("tenant-order-key", "tenant-order-key") in calls


def test_invalid_bcrypt_hash_fails_closed_with_401(
    tmp_path: Path,
    security_config_path: Path,
    db_path: Path,
) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "key_hash": "not-a-valid-bcrypt-hash",
                        "name": "Broken Agent",
                        "tenant": "acme",
                        "rate_limit_rpm": 5,
                        "allowed_entity_types": ["order"],
                        "created_at": "2026-04-10",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    client = TestClient(
        _build_app(api_keys_path, security_config_path, db_path),
        raise_server_exceptions=False,
    )

    response = client.get("/v1/entity/order/ORD-1", headers={"X-API-Key": "tenant-order-key"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key. Pass X-API-Key header."


def test_legacy_plaintext_keys_use_constant_time_compare(
    tmp_path: Path,
    security_config_path: Path,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.serving.api import auth as auth_module

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "key": "legacy-plaintext-key",
                        "name": "Legacy Agent",
                        "tenant": "acme",
                        "rate_limit_rpm": 5,
                        "allowed_entity_types": ["order"],
                        "created_at": "2026-04-10",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    calls: list[tuple[str, str]] = []

    def fake_compare_digest(left: str, right: str) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setattr(auth_module.secrets, "compare_digest", fake_compare_digest)
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
    )

    manager.load()
    tenant_key = manager.authenticate("legacy-plaintext-key")

    assert tenant_key is not None
    assert tenant_key.name == "Legacy Agent"
    assert calls == [("legacy-plaintext-key", "legacy-plaintext-key")]


def test_create_key_persists_hash_only(
    tmp_path: Path,
    security_config_path: Path,
    db_path: Path,
) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.write_text("keys: []\n", encoding="utf-8", newline="\n")
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
    )
    manager.load()

    created = manager.create_key(
        KeyCreateRequest(
            name="Support Agent",
            tenant="acme",
            rate_limit_rpm=7,
            allowed_entity_types=["order"],
        )
    )

    stored = yaml.safe_load(api_keys_path.read_text(encoding="utf-8"))

    assert created.key.startswith("af-")
    assert stored["keys"][0]["key_hash"].startswith("$2")
    assert "key" not in stored["keys"][0]
    assert created.key not in api_keys_path.read_text(encoding="utf-8")


def test_security_headers_are_added_to_successful_responses(
    api_keys_path: Path,
    security_config_path: Path,
    db_path: Path,
) -> None:
    from src.serving.api.security import SECURITY_HEADERS

    client = TestClient(_build_app(api_keys_path, security_config_path, db_path))

    response = client.get("/v1/entity/order/ORD-1", headers={"X-API-Key": "tenant-order-key"})

    assert response.status_code == 200
    for header_name, header_value in SECURITY_HEADERS.items():
        assert response.headers[header_name] == header_value


def test_security_headers_are_added_to_unauthorized_responses(
    api_keys_path: Path,
    security_config_path: Path,
    db_path: Path,
) -> None:
    from src.serving.api.security import SECURITY_HEADERS

    client = TestClient(_build_app(api_keys_path, security_config_path, db_path))

    response = client.get("/v1/entity/order/ORD-1", headers={"X-API-Key": "bad-key"})

    assert response.status_code == 401
    for header_name, header_value in SECURITY_HEADERS.items():
        assert response.headers[header_name] == header_value


def test_request_size_limit_blocks_oversized_bodies(
    api_keys_path: Path,
    db_path: Path,
    tmp_path: Path,
) -> None:
    security_config_path = tmp_path / "config" / "security.yaml"
    _write_security_config(security_config_path)
    client = TestClient(_build_app(api_keys_path, security_config_path, db_path))

    response = client.post(
        "/v1/query",
        headers={"X-API-Key": "tenant-order-key"},
        content=b"x" * (1_048_576 + 1),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large."


def test_failed_auth_is_throttled_by_ip_after_limit(
    api_keys_path: Path,
    db_path: Path,
    tmp_path: Path,
) -> None:
    security_config_path = tmp_path / "config" / "security.yaml"
    _write_security_config(security_config_path, max_failed_auth_per_ip_per_hour=10)
    client = TestClient(_build_app(api_keys_path, security_config_path, db_path))
    headers = {"X-API-Key": "bad-key", "X-Forwarded-For": "203.0.113.10"}

    responses = [client.get("/v1/entity/order/ORD-1", headers=headers) for _ in range(11)]

    assert all(response.status_code == 401 for response in responses[:10])
    assert responses[10].status_code == 429


def test_failed_auth_limit_resets_after_one_hour(
    api_keys_path: Path,
    db_path: Path,
    tmp_path: Path,
) -> None:
    security_config_path = tmp_path / "config" / "security.yaml"
    _write_security_config(security_config_path, max_failed_auth_per_ip_per_hour=2)
    clock = FrozenClock()
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
        time_source=clock,
    )
    manager.load()
    manager.ensure_usage_table()
    from src.serving.api.security import build_security_headers_middleware

    app = FastAPI()
    app.state.auth_manager = manager
    app.middleware("http")(build_auth_middleware())
    app.middleware("http")(build_security_headers_middleware())

    @app.get("/v1/entity/{entity_type}/{entity_id}")
    async def get_entity(entity_type: str, entity_id: str):
        return {"entity_type": entity_type, "entity_id": entity_id}

    client = TestClient(app)
    headers = {"X-API-Key": "bad-key", "X-Forwarded-For": "203.0.113.20"}

    first = client.get("/v1/entity/order/ORD-1", headers=headers)
    second = client.get("/v1/entity/order/ORD-1", headers=headers)
    third = client.get("/v1/entity/order/ORD-1", headers=headers)
    clock.advance(3601)
    fourth = client.get("/v1/entity/order/ORD-1", headers=headers)

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert fourth.status_code == 401


def test_rate_limit_blocks_121st_request_exactly(
    api_keys_path: Path,
    security_config_path: Path,
    db_path: Path,
) -> None:
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
    )

    manager.load()
    tenant_key = manager.authenticate("tenant-order-key")

    assert tenant_key is not None
    tenant_key = tenant_key.model_copy(update={"rate_limit_rpm": 120})
    assert all(not manager.is_rate_limited(tenant_key) for _ in range(120))
    assert manager.is_rate_limited(tenant_key) is True


def test_ensure_usage_table_retries_transient_duckdb_locks(
    api_keys_path: Path,
    security_config_path: Path,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.serving.api import auth as auth_module

    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        security_config_path=security_config_path,
    )
    attempts = {"count": 0}
    original_connect = auth_module.duckdb.connect

    def flaky_connect(path: str):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise auth_module.duckdb.Error("database is locked")
        return original_connect(path)

    monkeypatch.setattr(auth_module.duckdb, "connect", flaky_connect)

    manager.ensure_usage_table()

    assert attempts["count"] == 3


def test_redact_sensitive_headers_masks_secrets() -> None:
    from src.serving.api.security import redact_sensitive_headers

    headers = redact_sensitive_headers(
        {
            "Authorization": "Bearer secret-token",
            "X-API-Key": "af-secret",
            "X-Request-Id": "req-1",
        }
    )

    assert headers["Authorization"] == "[REDACTED]"
    assert headers["X-API-Key"] == "[REDACTED]"
    assert headers["X-Request-Id"] == "req-1"


def test_failed_auth_logs_redacted_headers(
    api_keys_path: Path,
    security_config_path: Path,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.serving.api import auth as auth_module

    events: list[tuple[str, dict]] = []

    class FakeLogger:
        def info(self, event: str, **kwargs) -> None:
            return None

        def warning(self, event: str, **kwargs) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(auth_module, "logger", FakeLogger())
    client = TestClient(_build_app(api_keys_path, security_config_path, db_path))

    response = client.get(
        "/v1/entity/order/ORD-1",
        headers={
            "X-API-Key": "bad-key",
            "Authorization": "Bearer secret-token",
            "X-Forwarded-For": "203.0.113.30",
        },
    )

    assert response.status_code == 401
    assert events[0][0] == "api_auth_failed"
    assert events[0][1]["headers"]["x-api-key"] == "[REDACTED]"
    assert events[0][1]["headers"]["authorization"] == "[REDACTED]"


def test_load_security_policy_reads_yaml(security_config_path: Path) -> None:
    from src.serving.api.security import load_security_policy

    policy = load_security_policy(security_config_path)

    assert policy.bcrypt_rounds == 4
    assert policy.max_failed_auth_per_ip_per_hour == 10
    assert policy.sensitive_headers_to_redact == ["Authorization", "X-API-Key"]


def test_rotate_keys_script_prints_plaintext_once_and_writes_hash(
    tmp_path: Path,
    security_config_path: Path,
) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.write_text("keys: []\n", encoding="utf-8", newline="\n")
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "rotate_keys.py"

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(script_path),
            "--api-keys",
            str(api_keys_path),
            "--security-config",
            str(security_config_path),
            "--name",
            "Support Agent",
            "--tenant",
            "acme",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    match = re.search(r"(af-[A-Za-z0-9_-]+)", completed.stdout)
    stored = yaml.safe_load(api_keys_path.read_text(encoding="utf-8"))

    assert match is not None
    assert stored["keys"][0]["key_hash"].startswith("$2")
    assert match.group(1) not in api_keys_path.read_text(encoding="utf-8")
