"""Narrow, duckdb-free mutation test for the PII masker.

This is the test the mutation gate runs against src/serving/masking.py (see
scripts/mutation_report.py MODULE_TARGETS). masking imports only hashlib /
pathlib / sqlglot / yaml -- no duckdb -- so, like sql_guard, it is mutated as a
top-level ``serving`` package against a test that stays off the duckdb-backed
engine import chain.

A surviving mutant in PII redaction is a cleartext-PII leak, so this exercises
every strategy branch (full / hash / partial / passthrough / None) and every
``_partial_mask`` shape (email / phone / address / multi-word / single word),
pinning the exact masked output so value-level mutants die.
"""

import hashlib

import pytest

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.masking import PiiMasker
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.masking import PiiMasker

CONFIG_YAML = """\
masking:
  default_strategy: partial
  entity_fields:
    user:
      - field: email
        strategy: partial
      - field: ip_address
        strategy: hash
      - field: ssn
        strategy: full
      - field: untouched
        strategy: passthrough
      - field: nickname
    order:
      - field: shipping_address
        strategy: partial
  pii_exempt_tenants:
    - internal-analytics
"""


@pytest.fixture
def masker(tmp_path):
    cfg = tmp_path / "pii_fields.yaml"
    cfg.write_text(CONFIG_YAML, encoding="utf-8")
    return PiiMasker(config_path=cfg)


def test_exempt_tenant_returns_unmasked_copy(masker):
    data = {"email": "alice@example.com"}
    out = masker.mask("user", data, "internal-analytics")
    assert out == {"email": "alice@example.com"}
    assert out is not data  # a copy, not the original


def test_non_exempt_tenant_masks_email(masker):
    out = masker.mask("user", {"email": "alice@example.com"}, "acme")
    assert out["email"] == "a***@example.com"


def test_hash_strategy(masker):
    out = masker.mask("user", {"ip_address": "10.0.0.1"}, "acme")
    assert out["ip_address"] == hashlib.sha256(b"10.0.0.1").hexdigest()[:12]


def test_full_strategy(masker):
    assert masker.mask("user", {"ssn": "123-45-6789"}, "acme")["ssn"] == "***"


def test_unknown_strategy_passes_value_through(masker):
    out = masker.mask("user", {"untouched": "keep-me"}, "acme")
    assert out["untouched"] == "keep-me"


def test_rule_without_strategy_uses_default(masker):
    # nickname has no strategy -> default_strategy (partial) applies.
    assert masker.mask("user", {"nickname": "Bobby"}, "acme")["nickname"] == "B***"


def test_field_absent_is_skipped(masker):
    out = masker.mask("user", {"other": "x"}, "acme")
    assert out == {"other": "x"}


def test_unknown_entity_returns_copy(masker):
    out = masker.mask("widget", {"email": "a@b.com"}, "acme")
    assert out == {"email": "a@b.com"}


def test_mask_query_results_masks_matched_entity(masker):
    rows = [{"email": "alice@example.com"}]
    masked, changed = masker.mask_query_results(
        "SELECT email FROM users_v2", rows, "acme", {"users_v2": "user"}
    )
    assert masked[0]["email"] == "a***@example.com"
    assert changed is True


def test_mask_query_results_no_entity_passthrough(masker):
    rows = [{"email": "alice@example.com"}]
    masked, changed = masker.mask_query_results(
        "SELECT email FROM unknown_t", rows, "acme", {"users_v2": "user"}
    )
    assert masked[0]["email"] == "alice@example.com"
    assert changed is False


def test_mask_query_results_unparseable_sql_passes_through(masker):
    masked, changed = masker.mask_query_results(
        "NOT SQL (((", [{"email": "a@b.com"}], "acme", {"users_v2": "user"}
    )
    assert changed is False


def test_mask_query_results_multi_entity_join_masks_both(masker):
    rows = [{"email": "alice@example.com", "shipping_address": "123 Main St, Town"}]
    masked, changed = masker.mask_query_results(
        "SELECT * FROM users_v2 JOIN orders_v2 ON 1=1",
        rows,
        "acme",
        {"users_v2": "user", "orders_v2": "order"},
    )
    assert masked[0]["email"] == "a***@example.com"
    assert masked[0]["shipping_address"] != "123 Main St, Town"
    assert changed is True


# --- _partial_mask shapes (via _apply_strategy partial) ----------------------


def test_partial_email_empty_local(masker):
    assert masker._mask_email("@example.com") == "***@example.com"


def test_partial_phone(masker):
    assert masker._partial_mask("+1 (234) 567-8900") == "***-***-8900"


def test_phone_without_digits_is_starred(masker):
    assert masker._mask_phone("no-digits-here-xxxxxxx") == "***"


def test_partial_address_with_number(masker):
    assert masker._partial_mask("123 Main St, Springfield") == "123 *** St, ***"


def test_address_street_without_number(masker):
    assert masker._mask_address("Main Street") == "M*** S***"


def test_partial_multiword_name(masker):
    assert masker._partial_mask("John Ronald Doe") == "J*** R*** D***"


def test_partial_single_word(masker):
    assert masker._partial_mask("Madonna") == "M***"


def test_partial_empty_string(masker):
    assert masker._partial_mask("") == ""


def test_apply_strategy_none_stays_none(masker):
    assert masker._apply_strategy(None, "full") is None


def test_mask_word_empty(masker):
    assert masker._mask_word("") == ""


def test_looks_like_phone_true_false(masker):
    assert masker._looks_like_phone("+1 234 567 8900") is True
    assert masker._looks_like_phone("hello world") is False


def test_looks_like_address_true_false(masker):
    assert masker._looks_like_address("12 Main") is True
    assert masker._looks_like_address("nodigits") is False
