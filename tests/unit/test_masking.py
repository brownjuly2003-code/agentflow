from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.serving.api.routers.agent_query as agent_query_module
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.masking import PiiMasker
from src.serving.semantic_layer.catalog import DataCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pii_fields.yaml"


def _write_pii_config(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def _reset_router_masker(monkeypatch, config_path: Path) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(config_path))
    monkeypatch.setattr(agent_query_module, "_PII_MASKER", None, raising=False)


class EngineStub:
    def __init__(self, payload: dict):
        self.payload = payload

    def get_entity(self, entity_type: str, entity_id: str) -> dict:
        return dict(self.payload)


def _build_client(payload: dict, tenant: str = "acme") -> TestClient:
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = EngineStub(payload)

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant_key = SimpleNamespace(tenant=tenant)
        return await call_next(request)

    app.include_router(agent_router, prefix="/v1")
    return TestClient(app)


def test_masker_partially_masks_email_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"email": "jane@example.com"}, tenant="acme")

    assert masked["email"] == "j***@example.com"


def test_masker_partially_masks_phone_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"phone": "555-123-4567"}, tenant="acme")

    assert masked["phone"] == "***-***-4567"


def test_masker_partially_masks_full_name_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"full_name": "Jane Doe"}, tenant="acme")

    assert masked["full_name"] == "J*** D***"


def test_masker_hashes_ip_addresses_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"ip_address": "203.0.113.10"}, tenant="acme")

    assert masked["ip_address"] == hashlib.sha256(b"203.0.113.10").hexdigest()[:12]


def test_masker_uses_custom_config_as_single_source_of_truth(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            order:
              - field: user_id
                strategy: full
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("order", {"user_id": "USR-1", "status": "delivered"}, tenant="acme")

    assert masked == {"user_id": "***", "status": "delivered"}


def test_masker_skips_pii_exempt_tenant():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    payload = {"email": "jane@example.com", "full_name": "Jane Doe"}

    masked = masker.mask("user", payload, tenant="internal-analytics")

    assert masked == payload


def test_masker_ignores_missing_fields():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    payload = {"status": "delivered"}

    masked = masker.mask("order", payload, tenant="acme")

    assert masked == payload


def test_mask_query_results_masks_single_entity(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    rows, masked = masker.mask_query_results(
        "SELECT email FROM users",
        [{"email": "jane@example.com"}],
        tenant="acme",
        table_to_entity={"users": "user"},
    )

    assert masked is True
    assert rows == [{"email": "j***@example.com"}]


def _user_email_config(tmp_path: Path) -> Path:
    return _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )


def test_mask_query_results_masks_aliased_pii_column(tmp_path: Path):
    # `email AS contact` previously bypassed masking: the output key was
    # "contact", not the rule field "email", so the cleartext address was
    # returned with no X-PII-Masked signal. Projection lineage now masks the
    # column derived from email. (audit_30_06_26.md D2)
    masker = PiiMasker(_user_email_config(tmp_path))

    rows, masked = masker.mask_query_results(
        "SELECT email AS contact FROM users_enriched",
        [{"contact": "alice@example.com"}],
        tenant="acme",
        table_to_entity={"users_enriched": "user"},
    )

    assert masked is True
    assert rows == [{"contact": "a***@example.com"}]


def test_mask_query_results_masks_derived_pii_column(tmp_path: Path):
    # A derived expression over a PII column is masked by what it's built from.
    masker = PiiMasker(_user_email_config(tmp_path))

    rows, masked = masker.mask_query_results(
        "SELECT lower(email) AS e FROM users_enriched",
        [{"e": "alice@example.com"}],
        tenant="acme",
        table_to_entity={"users_enriched": "user"},
    )

    assert masked is True
    assert rows == [{"e": "a***@example.com"}]


def test_mask_query_results_masks_pii_renamed_through_subquery(tmp_path: Path):
    # An inner rename hides the PII source name from the outer projection, so the
    # one-level lineage resolver saw only the renamed output column and returned
    # cleartext (the D2 fix's subquery/CTE-alias bypass). True lineage traces the
    # output column back to `email` through the subquery/CTE. (audit_30 D2 follow-up)
    masker = PiiMasker(_user_email_config(tmp_path))

    for sql, out_col in (
        ("SELECT contact FROM (SELECT email AS contact FROM users_enriched) t", "contact"),
        (
            "WITH t AS (SELECT email AS contact FROM users_enriched) SELECT contact FROM t",
            "contact",
        ),
        (
            "SELECT outer_c FROM (SELECT inner_c AS outer_c "
            "FROM (SELECT email AS inner_c FROM users_enriched) a) b",
            "outer_c",
        ),
    ):
        rows, masked = masker.mask_query_results(
            sql,
            [{out_col: "alice@example.com"}],
            tenant="acme",
            table_to_entity={"users_enriched": "user"},
        )

        assert masked is True, sql
        assert rows == [{out_col: "a***@example.com"}], sql


def test_mask_query_results_masks_pii_renamed_above_inner_select_star(tmp_path: Path):
    # A SELECT * *below* an inner rename defeats both #123 lineage paths: lineage
    # walks past the renamed `email` node to the bare `*` leaf and returned a
    # plain frozenset({'*'}) — not the unresolved sentinel (that only fires on a
    # lineage *exception*) — so `email` was never in the source set and the
    # column failed open as cleartext; the shallow scan sees only the outer alias.
    # A `*` leaf means the column could carry any source column (incl. PII), so it
    # must fail closed. (audit_30 D2 follow-up: SELECT*-blinded inner-rename bypass
    # of #123 — distinct from the subquery/CTE renames above, which keep a
    # resolvable lineage leaf.)
    masker = PiiMasker(_user_email_config(tmp_path))

    for sql in (
        "SELECT c FROM (SELECT email AS c FROM (SELECT * FROM users_enriched) z) t",
        "WITH z AS (SELECT * FROM users_enriched), y AS (SELECT email AS c FROM z) SELECT c FROM y",
    ):
        rows, masked = masker.mask_query_results(
            sql,
            [{"c": "alice@example.com"}],
            tenant="acme",
            table_to_entity={"users_enriched": "user"},
        )

        assert masked is True, sql
        assert rows == [{"c": "a***@example.com"}], sql


def test_mask_query_results_masks_unaliased_pii_expression(tmp_path: Path):
    # An unaliased expression over PII has no `alias_or_name`, so the resolver
    # skipped it and the output column kept DuckDB's rendered name (`upper(email)`,
    # `(email || '')`) — which never matched a rule field, so cleartext leaked.
    # Aligning projections positionally to the real result keys maps the column to
    # the source it references and masks it. (audit_30 D2 follow-up: unaliased-expr)
    masker = PiiMasker(_user_email_config(tmp_path))

    for sql, out_col in (
        ("SELECT upper(email) FROM users_enriched", "upper(email)"),
        ("SELECT email || '' FROM users_enriched", "(email || '')"),
    ):
        rows, masked = masker.mask_query_results(
            sql,
            [{out_col: "alice@example.com"}],
            tenant="acme",
            table_to_entity={"users_enriched": "user"},
        )

        assert masked is True, sql
        assert rows == [{out_col: "a***@example.com"}], sql


def test_mask_query_results_does_not_overmask_directly_named_nonpii(tmp_path: Path):
    # Positional alignment must key each projection to its *own* result column: a
    # directly-named non-PII column alongside a PII one stays untouched (no star,
    # no derivation -> resolvable lineage, not the fail-closed sentinel).
    masker = PiiMasker(_user_email_config(tmp_path))

    rows, masked = masker.mask_query_results(
        "SELECT email, user_id FROM users_enriched",
        [{"email": "alice@example.com", "user_id": "U-1"}],
        tenant="acme",
        table_to_entity={"users_enriched": "user"},
    )

    assert masked is True
    assert rows == [{"email": "a***@example.com", "user_id": "U-1"}]


def test_mask_query_results_masks_select_star_by_name(tmp_path: Path):
    # SELECT * has no resolvable projection lineage; masking falls back to
    # matching rule fields against the (canonical) output column names.
    masker = PiiMasker(_user_email_config(tmp_path))

    rows, masked = masker.mask_query_results(
        "SELECT * FROM users_enriched",
        [{"email": "alice@example.com", "user_id": "U-1"}],
        tenant="acme",
        table_to_entity={"users_enriched": "user"},
    )

    assert masked is True
    assert rows == [{"email": "a***@example.com", "user_id": "U-1"}]


def test_mask_query_results_masks_union_when_multiple_entities(tmp_path: Path):
    """A multi-entity JOIN must mask the union of all matched entities, not fail
    open. The old behaviour returned cleartext PII for any query touching !=1
    entity table — a reproduced cross-entity leak (audit_28_06_26.md #6)."""
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
            order:
              - field: user_id
                strategy: full
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    rows, masked = masker.mask_query_results(
        "SELECT u.email, o.user_id FROM users u JOIN orders o ON u.id = o.user_id",
        [{"email": "jane@example.com", "user_id": "U-123"}],
        tenant="acme",
        table_to_entity={"users": "user", "orders": "order"},
    )

    assert masked is True
    # both entities' rules are applied: user.email (partial) AND order.user_id (full)
    assert rows[0]["email"] == "j***@example.com"
    assert rows[0]["user_id"] != "U-123"


def test_mask_query_results_returns_unchanged_for_unmapped_table(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    rows, masked = masker.mask_query_results(
        "SELECT email FROM analytics_events",
        [{"email": "jane@example.com"}],
        tenant="acme",
        table_to_entity={"users": "user"},
    )

    assert masked is False
    assert rows == [{"email": "jane@example.com"}]


def test_mask_query_results_handles_unparseable_sql(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    rows, masked = masker.mask_query_results(
        "SELECT (((",
        [{"email": "jane@example.com"}],
        tenant="acme",
        table_to_entity={"users": "user"},
    )

    assert masked is False
    assert rows == [{"email": "jane@example.com"}]


def test_mask_query_results_reports_no_change_when_field_absent(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    rows, masked = masker.mask_query_results(
        "SELECT status FROM users",
        [{"status": "active"}],
        tenant="acme",
        table_to_entity={"users": "user"},
    )

    assert masked is False
    assert rows == [{"status": "active"}]


def test_mask_leaves_none_values_untouched(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"email": None}, tenant="acme")

    assert masked == {"email": None}


def test_mask_passes_through_unknown_strategy(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: tokenize
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"email": "jane@example.com"}, tenant="acme")

    assert masked == {"email": "jane@example.com"}


def test_mask_handles_empty_string_partial(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"email": ""}, tenant="acme")

    assert masked == {"email": ""}


def test_mask_email_with_empty_local_part(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: email
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"email": "@example.com"}, tenant="acme")

    assert masked == {"email": "***@example.com"}


def test_mask_single_token_name(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: full_name
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"full_name": "Madonna"}, tenant="acme")

    assert masked == {"full_name": "M***"}


def test_mask_partially_masks_numbered_street_address(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: address
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"address": "123 Main St, Springfield"}, tenant="acme")

    assert masked == {"address": "123 *** St, ***"}


def test_mask_partially_masks_single_part_address(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: address
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"address": "123 Main St"}, tenant="acme")

    assert masked == {"address": "123 *** St"}


def test_mask_partially_masks_address_without_leading_number(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            user:
              - field: address
                strategy: partial
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("user", {"address": "Main Apt, Building 5"}, tenant="acme")

    assert masked == {"address": "M*** A***, ***"}


def test_mask_word_returns_empty_for_empty_input():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    assert masker._mask_word("") == ""


def test_entity_endpoint_masks_data_and_sets_header(monkeypatch):
    _reset_router_masker(monkeypatch, DEFAULT_CONFIG_PATH)
    client = _build_client(
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
    assert response.json()["data"]["email"] == "j***@example.com"


def test_entity_endpoint_skips_masking_for_exempt_tenant(monkeypatch):
    _reset_router_masker(monkeypatch, DEFAULT_CONFIG_PATH)
    client = _build_client(
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
