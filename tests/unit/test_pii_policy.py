"""Unit + integration coverage for the bounded PII deny/redact policy.

Replaces test_masking.py. The old masker tried to *mask* PII in query results via
SQL lineage (bypassed 3×); this replacement *denies* PII queries at the guard and
*redacts* PII fields on the entity path. Three layers are pinned here:

* ``PiiPolicy.redact_entity`` — the entity-path redaction (constant sentinel).
* ``_prepare_nl_sql`` — the engine wiring that rejects a PII query before it runs.
* the ``/v1/entity`` route — the redaction + ``X-PII-Masked`` header end to end.

The deny-gate logic itself (``assert_no_pii_access``) is exhaustively pinned in
test_sql_guard_mutation.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.serving.api.routers.agent_query import router as agent_router
from src.serving.pii_policy import REDACTED, PiiPolicy, get_pii_policy
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query.nl_queries import UnsafeNLQueryError, _prepare_nl_sql

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pii_fields.yaml"


# ── PiiPolicy.redact_entity ──────────────────────────────────────


def test_redact_entity_replaces_declared_pii_fields_with_sentinel() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    redacted = policy.redact_entity(
        "user",
        {"email": "jane@example.com", "phone": "555-1234", "user_id": "USR-1"},
        "acme",
    )
    assert redacted == {"email": REDACTED, "phone": REDACTED, "user_id": "USR-1"}


def test_redact_entity_leaves_non_pii_entity_untouched() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    payload = {"product_id": "P-1", "name": "Widget"}
    assert policy.redact_entity("product", payload, "acme") == payload


def test_redact_entity_skips_exempt_tenant() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    payload = {"email": "jane@example.com", "full_name": "Jane Doe"}
    assert policy.redact_entity("user", payload, "internal-analytics") == payload


def test_redact_entity_leaves_none_values_untouched() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    # A None PII field is not redacted — there is nothing to leak, and replacing it
    # would falsely signal data existed (keeps X-PII-Masked off when all PII absent).
    assert policy.redact_entity("user", {"email": None, "status": "x"}, "acme") == {
        "email": None,
        "status": "x",
    }


def test_redact_entity_ignores_absent_pii_fields() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    assert policy.redact_entity("user", {"status": "active"}, "acme") == {"status": "active"}


def test_redact_entity_returns_a_copy() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    original = {"email": "jane@example.com"}
    policy.redact_entity("user", original, "acme")
    assert original == {"email": "jane@example.com"}  # input not mutated


def test_is_exempt() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    assert policy.is_exempt("internal-analytics") is True
    assert policy.is_exempt("compliance-audit") is True
    assert policy.is_exempt("acme") is False
    assert policy.is_exempt(None) is False


def test_pii_fields_for_entity() -> None:
    policy = PiiPolicy(DEFAULT_CONFIG_PATH)
    assert policy.pii_fields_for_entity("user") == frozenset(
        {"email", "phone", "full_name", "ip_address"}
    )
    assert policy.pii_fields_for_entity("order") == frozenset({"shipping_address"})
    assert policy.pii_fields_for_entity("nonexistent") == frozenset()


def test_custom_config_is_single_source_of_truth(tmp_path: Path) -> None:
    config = tmp_path / "pii.yaml"
    config.write_text(
        "masking:\n"
        "  entity_fields:\n"
        "    order:\n"
        "      - field: buyer_email\n"
        "  pii_exempt_tenants:\n"
        '    - "ops"\n',
        encoding="utf-8",
    )
    policy = PiiPolicy(config)
    # Only the custom config's fields are PII; the default user/email is not here.
    assert policy.pii_fields_for_entity("order") == frozenset({"buyer_email"})
    assert policy.pii_fields_for_entity("user") == frozenset()
    assert policy.is_exempt("ops") is True
    assert policy.redact_entity("order", {"buyer_email": "a@b.c"}, "x") == {"buyer_email": REDACTED}


def test_get_pii_policy_caches_and_rebuilds_on_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    first = get_pii_policy()
    assert get_pii_policy() is first  # cached when the path is unchanged

    other = tmp_path / "pii.yaml"
    other.write_text("masking:\n  entity_fields: {}\n  pii_exempt_tenants: []\n", encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(other))
    rebuilt = get_pii_policy()
    assert rebuilt is not first  # rebuilt when the configured path moves


# ── Engine deny-gate wiring (_prepare_nl_sql) ────────────────────

_USER_TABLES = {"users_enriched"}
_USER_MAP = {"users_enriched": "user"}


def test_prepare_nl_sql_denies_pii_query_for_nonexempt_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    with pytest.raises(UnsafeNLQueryError, match="PII column"):
        _prepare_nl_sql(
            "SELECT email FROM users_enriched",
            _USER_TABLES,
            table_to_entity=_USER_MAP,
            tenant_id="acme",
        )


def test_prepare_nl_sql_denies_select_star_over_pii_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    with pytest.raises(UnsafeNLQueryError, match="SELECT \\*"):
        _prepare_nl_sql(
            "SELECT * FROM users_enriched",
            _USER_TABLES,
            table_to_entity=_USER_MAP,
            tenant_id="acme",
        )


@pytest.mark.parametrize(
    "sql",
    [
        # DuckDB COLUMNS(...) expands to source columns (incl. PII) like a star,
        # but parses as exp.Columns, not exp.Star. (audit_01_07_26 deny-gate bypass)
        "SELECT COLUMNS('.*') FROM users_enriched",
        "SELECT COLUMNS('mail') FROM users_enriched",
        "SELECT COLUMNS(c -> c LIKE '%mail%') FROM users_enriched",
        "SELECT max(COLUMNS('.*')) FROM users_enriched",
    ],
)
def test_prepare_nl_sql_denies_columns_expansion_over_pii_table(
    monkeypatch: pytest.MonkeyPatch, sql: str
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    with pytest.raises(UnsafeNLQueryError, match="COLUMNS"):
        _prepare_nl_sql(sql, _USER_TABLES, table_to_entity=_USER_MAP, tenant_id="acme")


@pytest.mark.parametrize(
    "sql",
    [
        # DuckDB whole-row struct reference: a bare table name / alias in projection
        # returns a STRUCT of every column, PII included, naming no PII column and
        # using no star. (audit_01_07_26 deny-gate bypass)
        "SELECT users_enriched FROM users_enriched",
        "SELECT t FROM users_enriched AS t",
        "SELECT s FROM (SELECT users_enriched AS s FROM users_enriched) z",
    ],
)
def test_prepare_nl_sql_denies_whole_row_struct_reference_over_pii_table(
    monkeypatch: pytest.MonkeyPatch, sql: str
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    with pytest.raises(UnsafeNLQueryError, match="struct reference"):
        _prepare_nl_sql(sql, _USER_TABLES, table_to_entity=_USER_MAP, tenant_id="acme")


def test_prepare_nl_sql_allows_pii_query_for_exempt_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    sql = _prepare_nl_sql(
        "SELECT email FROM users_enriched",
        _USER_TABLES,
        table_to_entity=_USER_MAP,
        tenant_id="internal-analytics",
    )
    assert sql == "SELECT email FROM users_enriched"


def test_prepare_nl_sql_allows_nonpii_query_for_nonexempt_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    sql = _prepare_nl_sql(
        "SELECT COUNT(*) FROM users_enriched",
        _USER_TABLES,
        table_to_entity=_USER_MAP,
        tenant_id="acme",
    )
    assert sql == "SELECT COUNT(*) FROM users_enriched"


# ── /v1/entity endpoint (redaction + header) ─────────────────────


class _EntityEngineStub:
    def __init__(self, payload: dict):
        self.payload = payload

    def get_entity(self, entity_type: str, entity_id: str) -> dict:
        return dict(self.payload)


def _entity_client(payload: dict, tenant: str = "acme") -> TestClient:
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = _EntityEngineStub(payload)

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant_key = SimpleNamespace(tenant=tenant)
        return await call_next(request)

    app.include_router(agent_router, prefix="/v1")
    return TestClient(app)


def test_entity_endpoint_redacts_pii_and_sets_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    client = _entity_client(
        {
            "user_id": "USR-1",
            "email": "jane@example.com",
            "phone": "555-123-4567",
            "full_name": "Jane Doe",
            "ip_address": "203.0.113.10",
            "_last_updated": "2026-04-10T12:00:00+00:00",
        }
    )

    response = client.get("/v1/entity/user/USR-1")

    assert response.status_code == 200
    assert response.headers["X-PII-Masked"] == "true"
    data = response.json()["data"]
    assert data["email"] == REDACTED
    assert data["phone"] == REDACTED
    assert data["full_name"] == REDACTED
    assert data["ip_address"] == REDACTED
    assert data["user_id"] == "USR-1"  # non-PII preserved


def test_entity_endpoint_skips_redaction_for_exempt_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(DEFAULT_CONFIG_PATH))
    client = _entity_client(
        {
            "user_id": "USR-1",
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "_last_updated": "2026-04-10T12:00:00+00:00",
        },
        tenant="internal-analytics",
    )

    response = client.get("/v1/entity/user/USR-1")

    assert response.status_code == 200
    assert "X-PII-Masked" not in response.headers
    assert response.json()["data"]["email"] == "jane@example.com"
