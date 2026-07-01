"""Pin nl_engine's LLM path after it was rewired to the vendored engine.

ADR 0008 step 3: ``_llm_translate`` now routes through
``nl_sql_engine.generate_sql_text`` (LangGraph generate→validate→repair on
Sonnet 5 via GraceKelly) instead of a single-shot POST. These tests pin, without
a live GraceKelly:

- the ``GRACEKELLY_URL`` gate (unset → rule-based; set → engine);
- that the engine is called with a GraceKelly provider carrying the configured
  model + base URL;
- graceful degradation when the engine raises / returns nothing.
"""

from __future__ import annotations

import pytest

import src.serving.semantic_layer.nl_engine as nl_engine
import src.serving.semantic_layer.nl_sql_engine as engine_pkg
from src.serving.semantic_layer.catalog import DataCatalog


@pytest.fixture
def catalog() -> DataCatalog:
    return DataCatalog()


def test_translate_uses_rule_based_when_gracekelly_unset(
    catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nl_engine, "_GRACEKELLY_URL", "")
    # "revenue" hits the rule-based revenue template; the engine must NOT run.
    called = False

    def _boom(*args: object, **kwargs: object) -> str:
        nonlocal called
        called = True
        return "SELECT 1"

    monkeypatch.setattr(engine_pkg, "generate_sql_text", _boom)
    sql = nl_engine.translate_nl_to_sql("total revenue", catalog)
    assert sql is not None
    assert "orders_v2" in sql
    assert called is False


def test_translate_routes_to_engine_when_gracekelly_set(
    catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nl_engine, "_GRACEKELLY_URL", "http://gracekelly.test")
    monkeypatch.setattr(nl_engine, "_GK_NL_SQL_MODEL", "claude-sonnet-5")

    captured: dict[str, object] = {}

    def _fake_generate(question: str, cat: DataCatalog, *, provider: object) -> str:
        captured["question"] = question
        captured["provider"] = provider
        return "SELECT COUNT(*) FROM orders_v2"

    monkeypatch.setattr(engine_pkg, "generate_sql_text", _fake_generate)

    sql = nl_engine.translate_nl_to_sql("how many orders", catalog)
    assert sql == "SELECT COUNT(*) FROM orders_v2"
    assert captured["question"] == "how many orders"
    provider = captured["provider"]
    assert provider.model == "claude-sonnet-5"  # type: ignore[attr-defined]
    assert provider._base_url == "http://gracekelly.test"  # type: ignore[attr-defined]


def test_llm_translate_returns_none_on_provider_error(
    catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nl_engine, "_GRACEKELLY_URL", "http://gracekelly.test")

    def _raise(*args: object, **kwargs: object) -> str:
        raise engine_pkg.ProviderError("GraceKelly unreachable")

    monkeypatch.setattr(engine_pkg, "generate_sql_text", _raise)
    assert nl_engine.translate_nl_to_sql("q", catalog) is None


def test_llm_translate_returns_none_when_engine_yields_no_sql(
    catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nl_engine, "_GRACEKELLY_URL", "http://gracekelly.test")
    monkeypatch.setattr(engine_pkg, "generate_sql_text", lambda *a, **k: None)
    assert nl_engine.translate_nl_to_sql("q", catalog) is None
