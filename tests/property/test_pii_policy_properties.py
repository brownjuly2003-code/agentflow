"""Property tests for the bounded PII deny/redact policy.

Replaces test_masking_properties.py (which pinned the deleted partial-mask
patterns). The invariants now are: every declared PII field is redacted to the
constant sentinel for a non-exempt tenant regardless of value, exempt tenants are
never redacted, and the deny-gate rejects a query selecting any PII column.
"""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from src.serving.pii_policy import REDACTED, PiiPolicy
from src.serving.semantic_layer.sql_guard import UnsafeSQLError, assert_no_pii_access

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pii_fields.yaml"
_USER_PII_FIELDS = ["email", "phone", "full_name", "ip_address"]
_POLICY = PiiPolicy(_DEFAULT_CONFIG_PATH)
_MAP = {"users_enriched": "user"}
_FIELDS = {"user": _POLICY.pii_fields_for_entity("user")}


@given(field=st.sampled_from(_USER_PII_FIELDS), value=st.text(min_size=1))
def test_any_pii_value_is_redacted_to_the_sentinel(field: str, value: str) -> None:
    # Whatever the value, a non-exempt tenant gets the constant sentinel — never a
    # partial of the original (the old masker leaked first-char/domain/last-4).
    redacted = _POLICY.redact_entity("user", {field: value}, "acme")[field]
    assert redacted == REDACTED
    assert value not in str(redacted) or value == REDACTED


@given(
    email=st.emails(),
    phone=st.text(min_size=1),
    tenant=st.sampled_from(["internal-analytics", "compliance-audit"]),
)
def test_exempt_tenant_is_never_redacted(email: str, phone: str, tenant: str) -> None:
    payload = {"email": email, "phone": phone}
    assert _POLICY.redact_entity("user", payload, tenant) == payload


@given(field=st.sampled_from(_USER_PII_FIELDS))
def test_selecting_any_pii_column_is_denied(field: str) -> None:
    try:
        assert_no_pii_access(f"SELECT {field} FROM users_enriched", _MAP, _FIELDS)
    except UnsafeSQLError:
        return
    raise AssertionError(f"deny-gate let a PII column through: {field}")
