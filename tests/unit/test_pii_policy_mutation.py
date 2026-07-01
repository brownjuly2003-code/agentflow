"""Narrow, duckdb-free mutation test for the PII deny/redact policy.

This is the test the mutation gate runs against src/serving/pii_policy.py (see
scripts/mutation_report.py MODULE_TARGETS). pii_policy imports only os/yaml/pathlib,
so keeping this test free of the QueryEngine/duckdb import chain lets mutmut mutate
the module without dragging duckdb's compiled subpackage into its mutants/ workspace.

Dual-context import: under the mutation harness the module is copied to the
workspace as a top-level ``serving`` package (no ``src.`` prefix, which mutmut's
trampoline rejects); under ordinary pytest it lives under the ``src`` package.

Every assertion pins exact values (the sentinel string, the redacted/kept fields,
the exempt set, the parsed PII field sets) so the value/operator mutants die — a
surviving mutant here is a PII redaction or exemption regression.
"""

from pathlib import Path

import pytest

try:  # mutation-harness workspace exposes it as a top-level package
    import serving.pii_policy as pii_module
    from serving.pii_policy import REDACTED, PiiPolicy, get_pii_policy
except ImportError:  # ordinary pytest sees it under the src package
    import src.serving.pii_policy as pii_module
    from src.serving.pii_policy import REDACTED, PiiPolicy, get_pii_policy

_CONFIG = """
masking:
  entity_fields:
    user:
      - field: email
        strategy: partial
      - field: phone
        strategy: partial
    order:
      - field: shipping_address
        strategy: partial
  pii_exempt_tenants:
    - "internal-analytics"
    - "compliance-audit"
"""


def _policy(tmp_path: Path, body: str = _CONFIG) -> PiiPolicy:
    config = tmp_path / "pii_fields.yaml"
    config.write_text(body.strip() + "\n", encoding="utf-8")
    return PiiPolicy(config)


def test_sentinel_value(tmp_path: Path) -> None:
    # Pin the exact sentinel so a mutant that alters the redaction marker dies.
    assert REDACTED == "[REDACTED]"


def test_pii_fields_parsed_per_entity(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    assert policy.pii_fields_for_entity("user") == frozenset({"email", "phone"})
    assert policy.pii_fields_for_entity("order") == frozenset({"shipping_address"})
    assert policy.pii_fields_for_entity("product") == frozenset()


def test_init_skips_rules_without_a_field(tmp_path: Path) -> None:
    policy = _policy(
        tmp_path,
        "masking:\n"
        "  entity_fields:\n"
        "    user:\n"
        "      - field: email\n"
        "      - strategy: partial\n"  # no 'field' key -> skipped
        "      - not-a-mapping\n",  # non-dict -> skipped
    )
    assert policy.pii_fields_for_entity("user") == frozenset({"email"})


def test_init_empty_config_has_no_pii_and_no_exemptions(tmp_path: Path) -> None:
    policy = _policy(tmp_path, "masking:\n  entity_fields: {}\n  pii_exempt_tenants: []\n")
    assert policy.pii_fields_for_entity("user") == frozenset()
    assert policy.is_exempt("internal-analytics") is False


def test_is_exempt_true_only_for_listed_tenants(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    assert policy.is_exempt("internal-analytics") is True
    assert policy.is_exempt("compliance-audit") is True
    assert policy.is_exempt("acme") is False
    assert policy.is_exempt(None) is False
    assert policy.is_exempt("") is False


def test_redact_entity_redacts_each_declared_pii_field(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    out = policy.redact_entity(
        "user",
        {"email": "a@b.c", "phone": "555", "user_id": "U-1"},
        "acme",
    )
    assert out == {"email": REDACTED, "phone": REDACTED, "user_id": "U-1"}


def test_redact_entity_keeps_non_pii_entity(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    assert policy.redact_entity("product", {"sku": "X"}, "acme") == {"sku": "X"}


def test_redact_entity_exempt_tenant_unchanged(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    payload = {"email": "a@b.c", "phone": "555"}
    assert policy.redact_entity("user", payload, "internal-analytics") == payload


def test_redact_entity_leaves_none_untouched(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    assert policy.redact_entity("user", {"email": None, "phone": "5"}, "acme") == {
        "email": None,
        "phone": REDACTED,
    }


def test_redact_entity_does_not_mutate_input(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    payload = {"email": "a@b.c"}
    policy.redact_entity("user", payload, "acme")
    assert payload == {"email": "a@b.c"}


def test_redact_entity_skips_absent_pii_field(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    assert policy.redact_entity("user", {"user_id": "U-1"}, "acme") == {"user_id": "U-1"}


def test_default_config_path_constructs_from_repo_config() -> None:
    # No-arg construction must resolve the real default path relative to cwd
    # (the repo root under pytest; the also_copied `config/` dir inside the
    # mutmut workspace). Kills the default-ARGUMENT mutants that swap the path
    # string ("XXconfig...XX" / upper-cased): they point at a nonexistent file
    # and raise on construction, so merely constructing without a path dies.
    policy = PiiPolicy()
    assert policy.config_path == Path("config/pii_fields.yaml")
    assert isinstance(policy.pii_fields_by_entity, dict)


def test_get_pii_policy_uses_default_path_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With AGENTFLOW_PII_CONFIG unset the resolver must fall back to the real
    # default path. Kills the get_pii_policy default mutants: None -> Path(None)
    # raises TypeError; a bad/upper-cased string -> FileNotFoundError.
    pii_module._POLICY = None
    monkeypatch.delenv("AGENTFLOW_PII_CONFIG", raising=False)
    policy = get_pii_policy()
    assert policy.config_path == Path("config/pii_fields.yaml")


def test_get_pii_policy_caches_and_rebuilds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pii_module._POLICY = None
    first = tmp_path / "a.yaml"
    first.write_text("masking:\n  entity_fields: {}\n  pii_exempt_tenants: []\n", encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(first))
    p1 = get_pii_policy()
    assert get_pii_policy() is p1  # cached on unchanged path

    second = tmp_path / "b.yaml"
    second.write_text(
        "masking:\n  entity_fields: {}\n  pii_exempt_tenants:\n    - x\n", encoding="utf-8"
    )
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(second))
    p2 = get_pii_policy()
    assert p2 is not p1  # rebuilt when the path moves
    assert p2.is_exempt("x") is True
