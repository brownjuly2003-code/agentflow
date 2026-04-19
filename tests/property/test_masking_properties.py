from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from src.serving.masking import PiiMasker

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pii_fields.yaml"
_EMAILS = st.emails()
_PHONES = st.from_regex(r"\+1\d{10}", fullmatch=True)
_IP_ADDRESSES = st.tuples(
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
).map(lambda parts: ".".join(str(part) for part in parts))


@given(email=_EMAILS)
def test_email_masking_preserves_domain_and_changes_local_part(email: str) -> None:
    masker = PiiMasker(_DEFAULT_CONFIG_PATH)
    local, domain = email.split("@", 1)

    masked = masker.mask("user", {"email": email}, tenant="acme")["email"]

    assert masked != email
    assert masked.endswith(f"@{domain}")
    assert masked[0] == local[0]


@given(phone=_PHONES)
def test_phone_masking_preserves_last_four_digits(phone: str) -> None:
    masker = PiiMasker(_DEFAULT_CONFIG_PATH)
    last_four = "".join(character for character in phone if character.isdigit())[-4:]

    masked = masker.mask("user", {"phone": phone}, tenant="acme")["phone"]

    assert masked != phone
    assert masked.startswith("***-***-")
    assert masked.endswith(last_four)


@given(ip_address=_IP_ADDRESSES)
def test_ip_hash_masking_is_deterministic(ip_address: str) -> None:
    masker = PiiMasker(_DEFAULT_CONFIG_PATH)
    payload = {"ip_address": ip_address}

    first = masker.mask("user", payload, tenant="acme")["ip_address"]
    second = masker.mask("user", payload, tenant="acme")["ip_address"]

    assert first == second
    assert first != ip_address
    assert len(first) == 12


@given(email=_EMAILS, phone=_PHONES)
def test_exempt_tenant_bypasses_masking(email: str, phone: str) -> None:
    masker = PiiMasker(_DEFAULT_CONFIG_PATH)
    payload = {"email": email, "phone": phone}

    assert masker.mask("user", payload, tenant="internal-analytics") == payload
