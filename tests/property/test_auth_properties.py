from hypothesis import assume, given
from hypothesis import strategies as st

from src.serving.api.security import hash_api_key, verify_api_key

_KEY_STRATEGY = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=32,
)


@given(key=_KEY_STRATEGY)
def test_hash_verify_roundtrip(key: str) -> None:
    key_hash = hash_api_key(key, rounds=4)
    assert verify_api_key(key, key_hash)


@given(correct_key=_KEY_STRATEGY, wrong_key=_KEY_STRATEGY)
def test_wrong_key_never_verifies(correct_key: str, wrong_key: str) -> None:
    assume(correct_key != wrong_key)

    key_hash = hash_api_key(correct_key, rounds=4)

    assert not verify_api_key(wrong_key, key_hash)


@given(key=_KEY_STRATEGY)
def test_hash_output_is_bcrypt_encoded_and_not_plaintext(key: str) -> None:
    key_hash = hash_api_key(key, rounds=4)

    assert key_hash != key
    assert key_hash.startswith("$2")
    assert len(key_hash) > len(key)
