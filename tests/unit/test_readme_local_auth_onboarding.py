"""Docs-only pin: README Quick start open demo + own local API-key path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def test_readme_local_auth_onboarding_documents_open_demo_and_own_key() -> None:
    text = README.read_text(encoding="utf-8")
    plain_text = text.replace("**", "")

    assert "make demo" in text
    assert "curl http://localhost:8000/v1/entity/order/ORD-20260404-1001" in text
    assert "curl -X POST http://localhost:8000/v1/query" in text
    assert '{"question":"Show me top 3 products"}' in text
    assert (
        "Local demo runs without API-key enforcement unless you explicitly "
        "configure `AGENTFLOW_API_KEYS_FILE`."
    ) in text

    assert "cp .env.example .env" in text
    assert "python scripts/rotate_keys.py --name Local --tenant default" in text
    assert "plaintext" in text.lower()
    assert "shown once" in text.lower()
    assert "one-way hash" in text
    assert "AGENTFLOW_API_KEYS_FILE=config/api_keys.local.yaml" in text
    assert "$env:AGENTFLOW_API_KEYS_FILE = " in text
    assert "tracked `config/api_keys.yaml` remains a sample" in text
    assert "python -m uvicorn src.serving.api.main:app" in text
    assert "without `AGENTFLOW_AUTH_DISABLED`" in plain_text
    assert "X-API-Key" in text
    assert "demo-key" in text
    assert "public-demo-only" in text

    quick_start = text.split("## Architecture", 1)[0]
    assert "bcrypt" not in quick_start.lower()
