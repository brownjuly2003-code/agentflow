"""Narrow, duckdb-free mutation test for the PII masker (src/serving/masking.py).

This is the test the mutation gate runs against ``serving/masking.py`` (see
scripts/mutation_report.py MODULE_TARGETS). The masker protects cleartext PII, so
its masking logic is exactly the kind of code a mutation gate should pin.

Two design rules, both learned the hard way (see the masking entry in
fable_handoff.md cont.16):

1. **duckdb-free.** The ordinary ``tests/unit/test_masking.py`` imports the API
   router -> DataCatalog -> the duckdb engine chain, which drags duckdb's compiled
   subpackage into mutmut's ``mutants/`` workspace and crashes the run. This file
   imports only ``masking`` (hashlib/pathlib/sqlglot/yaml), so mutmut can mutate
   the module cleanly.

2. **No fixtures -- direct construction and direct method calls.** With
   ``mutate_only_covered_lines = true`` the gate first collects coverage; a
   fixture-built masker left every method line uncovered, so only ``__init__`` got
   mutated (score 0%). Building the masker inline and calling each method directly
   -- the same shape that made test_sql_guard_mutation.py work -- attributes every
   method line so the whole module is mutated.

Dual-context import: under the mutation harness the module is copied to the
workspace as a top-level ``serving`` package (no ``src.`` prefix, which mutmut's
trampoline rejects); under ordinary pytest it lives under the ``src`` package.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.masking import PiiMasker
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.masking import PiiMasker

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pii_fields.yaml"


def _masker(config: dict | None = None) -> PiiMasker:
    """Build a masker via the real __init__ (so its lines stay covered), then
    optionally swap in an explicit config so each behaviour is pinned without
    depending on the shipped config file."""
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    if config is not None:
        masker._config = config
    return masker


# --- __init__ + the shipped config (pins config load and the real rule set) ---


def test_init_stores_config_path():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    assert masker.config_path == Path(DEFAULT_CONFIG_PATH)


def test_real_config_partial_masks_email():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    assert masker.mask("user", {"email": "jane@example.com"}, "acme") == {
        "email": "j***@example.com"
    }


def test_real_config_hashes_ip_address():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    out = masker.mask("user", {"ip_address": "203.0.113.10"}, "acme")
    assert out["ip_address"] == hashlib.sha256(b"203.0.113.10").hexdigest()[:12]


def test_real_config_exempts_internal_analytics_tenant():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    payload = {"email": "jane@example.com"}
    assert masker.mask("user", payload, "internal-analytics") == payload


# --- mask(): tenant exemption, rule lookup, default strategy ---

_FULL_CFG = {
    "masking": {
        "pii_exempt_tenants": ["vip"],
        "entity_fields": {"user": [{"field": "email", "strategy": "full"}]},
    }
}


def test_mask_exempt_tenant_returns_unmasked_copy():
    masker = _masker(_FULL_CFG)
    data = {"email": "a@b.com"}
    out = masker.mask("user", data, "vip")
    assert out == {"email": "a@b.com"}
    assert out is not data  # copy, not the caller's dict


def test_mask_non_exempt_tenant_applies_rule():
    masker = _masker(_FULL_CFG)
    assert masker.mask("user", {"email": "a@b.com"}, "acme") == {"email": "***"}


def test_mask_uses_config_default_strategy_when_rule_omits_one():
    cfg = {
        "masking": {
            "default_strategy": "full",
            "entity_fields": {"user": [{"field": "email"}]},
            "pii_exempt_tenants": [],
        }
    }
    assert _masker(cfg).mask("user", {"email": "a@b.com"}, "acme") == {"email": "***"}


def test_mask_default_strategy_falls_back_to_partial():
    cfg = {
        "masking": {
            "entity_fields": {"user": [{"field": "email"}]},
            "pii_exempt_tenants": [],
        }
    }
    assert _masker(cfg).mask("user", {"email": "jane@example.com"}, "acme") == {
        "email": "j***@example.com"
    }


def test_mask_ignores_field_absent_from_data():
    cfg = {
        "masking": {
            "entity_fields": {"user": [{"field": "email", "strategy": "full"}]},
            "pii_exempt_tenants": [],
        }
    }
    assert _masker(cfg).mask("user", {"name": "x"}, "acme") == {"name": "x"}


def test_mask_unknown_entity_returns_unmodified_copy():
    masker = _masker({"masking": {"entity_fields": {}, "pii_exempt_tenants": []}})
    data = {"email": "a@b.com"}
    out = masker.mask("ghost", data, "acme")
    assert out == data
    assert out is not data


def test_mask_empty_config_returns_copy():
    masker = _masker({})
    data = {"email": "a@b.com"}
    out = masker.mask("user", data, "acme")
    assert out == data
    assert out is not data


# --- _apply_strategy() ---


def test_apply_strategy_none_value_stays_none():
    assert _masker()._apply_strategy(None, "full") is None


def test_apply_strategy_full_returns_stars():
    assert _masker()._apply_strategy("secret", "full") == "***"


def test_apply_strategy_hash_takes_first_twelve_hex_chars():
    masker = _masker()
    assert (
        masker._apply_strategy("203.0.113.10", "hash")
        == hashlib.sha256(b"203.0.113.10").hexdigest()[:12]
    )


def test_apply_strategy_hash_stringifies_non_str_value():
    masker = _masker()
    assert masker._apply_strategy(12345, "hash") == hashlib.sha256(b"12345").hexdigest()[:12]


def test_apply_strategy_partial_delegates_to_partial_mask():
    assert _masker()._apply_strategy("jane@example.com", "partial") == "j***@example.com"


def test_apply_strategy_unknown_passes_value_through():
    assert _masker()._apply_strategy("keepme", "tokenize") == "keepme"


# --- _partial_mask() branch selection ---


def test_partial_mask_empty_returns_input():
    assert _masker()._partial_mask("") == ""


def test_partial_mask_routes_single_at_to_email():
    assert _masker()._partial_mask("jane@example.com") == "j***@example.com"


def test_partial_mask_double_at_is_not_email():
    # count("@") == 2 -> skips the email branch, falls through to single-word mask.
    assert _masker()._partial_mask("a@b@c") == "a***"


def test_partial_mask_routes_phone():
    assert _masker()._partial_mask("555-123-4567") == "***-***-4567"


def test_partial_mask_routes_numbered_address():
    assert _masker()._partial_mask("123 Main St, Springfield") == "123 *** St, ***"


def test_partial_mask_multiword_name():
    assert _masker()._partial_mask("Jane Doe") == "J*** D***"


def test_partial_mask_single_word():
    assert _masker()._partial_mask("Madonna") == "M***"


def test_partial_mask_strips_before_space_check():
    # " Jane".strip() has no internal space -> single-word path masks the raw value
    # (leading space kept). Without .strip() it would split into ["Jane"].
    assert _masker()._partial_mask(" Jane") == " ***"


# --- _mask_email() ---


def test_mask_email_keeps_first_local_char():
    assert _masker()._mask_email("jane@example.com") == "j***@example.com"


def test_mask_email_empty_local_part():
    assert _masker()._mask_email("@example.com") == "***@example.com"


def test_mask_email_splits_on_first_at_only():
    # split("@", 1) keeps everything after the first @ as the domain; dropping the
    # maxsplit (or using rsplit) would mis-split a value with two @ signs.
    assert _masker()._mask_email("a@b@c") == "a***@b@c"


# --- _mask_phone() ---


def test_mask_phone_keeps_last_four_digits():
    assert _masker()._mask_phone("555-123-4567") == "***-***-4567"


def test_mask_phone_without_digits_returns_stars():
    assert _masker()._mask_phone("no-digits-here") == "***"


# --- _mask_address() ---


def test_mask_address_all_empty_parts_returns_stars():
    assert _masker()._mask_address(",,,") == "***"


def test_mask_address_numbered_single_token():
    assert _masker()._mask_address("123") == "123 ***"


def test_mask_address_numbered_keeps_first_and_last_street_token():
    assert _masker()._mask_address("123 Main St") == "123 *** St"


def test_mask_address_non_numbered_street_masks_each_token():
    assert _masker()._mask_address("Main Apt, Building 5") == "M*** A***, ***"


def test_mask_address_multi_part_stars_the_rest():
    assert _masker()._mask_address("123 Main St, Springfield") == "123 *** St, ***"


# --- _looks_like_phone() / _looks_like_address() boundaries ---


def test_looks_like_phone_true_at_seven_digits():
    assert _masker()._looks_like_phone("123 4567") is True


def test_looks_like_phone_false_below_seven_digits():
    assert _masker()._looks_like_phone("123456") is False


def test_looks_like_phone_false_when_letter_present():
    assert _masker()._looks_like_phone("12345678a") is False


def test_looks_like_phone_rejects_uppercase_letter_in_digit_run():
    # Pins that an alphabetic character is not an allowed phone character even with
    # enough digits, so it is not routed to phone masking.
    assert _masker()._looks_like_phone("1234567X") is False


def test_looks_like_address_true_with_digit_and_letter():
    assert _masker()._looks_like_address("123 Main") is True


def test_looks_like_address_false_without_digit():
    assert _masker()._looks_like_address("Main Street") is False


def test_looks_like_address_false_without_letter():
    assert _masker()._looks_like_address("12345") is False


# --- _mask_word() ---


def test_mask_word_keeps_first_char():
    assert _masker()._mask_word("Jane") == "J***"


def test_mask_word_empty_returns_input():
    assert _masker()._mask_word("") == ""


# --- mask_query_results() + _extract_table_names() ---

_QR_CFG = {
    "masking": {
        "default_strategy": "partial",
        "entity_fields": {
            "user": [{"field": "email", "strategy": "partial"}],
            "order": [{"field": "uid", "strategy": "full"}],
        },
        "pii_exempt_tenants": [],
    }
}


def test_mask_query_results_single_entity_masks_and_flags_change():
    masker = _masker(_QR_CFG)
    rows, changed = masker.mask_query_results(
        "SELECT email FROM users",
        [{"email": "jane@example.com"}],
        "acme",
        {"users": "user"},
    )
    assert changed is True
    assert rows == [{"email": "j***@example.com"}]


def test_mask_query_results_unmapped_table_passes_through_unchanged():
    masker = _masker(_QR_CFG)
    rows, changed = masker.mask_query_results(
        "SELECT email FROM events",
        [{"email": "jane@example.com"}],
        "acme",
        {"users": "user"},
    )
    assert changed is False
    assert rows == [{"email": "jane@example.com"}]


def test_mask_query_results_unparseable_sql_passes_through():
    masker = _masker(_QR_CFG)
    rows, changed = masker.mask_query_results(
        "SELECT (((",
        [{"email": "jane@example.com"}],
        "acme",
        {"users": "user"},
    )
    assert changed is False
    assert rows == [{"email": "jane@example.com"}]


def test_mask_query_results_reports_no_change_when_field_absent():
    masker = _masker(_QR_CFG)
    rows, changed = masker.mask_query_results(
        "SELECT status FROM users",
        [{"status": "active"}],
        "acme",
        {"users": "user"},
    )
    assert changed is False
    assert rows == [{"status": "active"}]


def test_mask_query_results_masks_union_of_all_matched_entities():
    masker = _masker(_QR_CFG)
    rows, changed = masker.mask_query_results(
        "SELECT u.email, o.uid FROM users u JOIN orders o ON u.id = o.uid",
        [{"email": "jane@example.com", "uid": "U-1"}],
        "acme",
        {"users": "user", "orders": "order"},
    )
    assert changed is True
    assert rows[0]["email"] == "j***@example.com"
    assert rows[0]["uid"] == "***"


def test_extract_table_names_collects_all_tables():
    assert _masker()._extract_table_names("SELECT a FROM orders JOIN users ON 1=1") == {
        "orders",
        "users",
    }


def test_extract_table_names_unparseable_returns_empty_set():
    assert _masker()._extract_table_names("SELECT (((") == set()
