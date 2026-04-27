from pathlib import Path

from src.serving.masking import PiiMasker

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pii_fields.yaml"


def test_mask_handles_quoted_schema_table() -> None:
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    rows, masked = masker.mask_query_results(
        'SELECT email FROM "acme"."users_enriched"',
        [{"email": "jane@example.com"}],
        "acme",
        {"users_enriched": "user"},
    )

    assert masked is True
    assert rows == [{"email": "j***@example.com"}]
