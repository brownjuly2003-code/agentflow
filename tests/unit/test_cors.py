import importlib

from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager


def test_default_origin_is_allowed_and_exposes_headers(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_CORS_ORIGINS", raising=False)
    main_module = importlib.import_module("src.serving.api.main")
    main_module = importlib.reload(main_module)
    main_module.app.state.auth_manager = AuthManager()
    main_module.app.state.auth_manager.load()
    client = TestClient(main_module.app)

    response = client.get("/does-not-exist", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-expose-headers"] == (
        "X-Cache, X-Request-Id, X-Process-Time"
    )


def test_blocked_origin_does_not_receive_cors_headers(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_CORS_ORIGINS", raising=False)
    main_module = importlib.import_module("src.serving.api.main")
    main_module = importlib.reload(main_module)
    main_module.app.state.auth_manager = AuthManager()
    main_module.app.state.auth_manager.load()
    client = TestClient(main_module.app)

    response = client.get("/does-not-exist", headers={"Origin": "https://evil.example"})

    assert response.status_code == 404
    assert "access-control-allow-origin" not in response.headers


def test_preflight_allows_any_origin_when_configured(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_CORS_ORIGINS", "*")
    main_module = importlib.import_module("src.serving.api.main")
    main_module = importlib.reload(main_module)
    main_module.app.state.auth_manager = AuthManager()
    main_module.app.state.auth_manager.load()
    client = TestClient(main_module.app)

    response = client.options(
        "/v1/health",
        headers={
            "Origin": "https://browser-agent.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://browser-agent.example"
