"""Static contract: Postgres enqueue stamps claim lease (multi-pod race).

Live exclusivity is covered by
``tests/integration/test_control_plane_postgres_live.py`` when a DSN is present.
This pin keeps the INSERT shape from regressing on hosts without PostgreSQL.
"""

from pathlib import Path

POSTGRES = Path(__file__).resolve().parents[2] / "src" / "serving" / "control_plane" / "postgres.py"


def test_enqueue_webhook_delivery_stamps_lease_on_insert() -> None:
    text = POSTGRES.read_text(encoding="utf-8")
    assert POSTGRES.is_file()

    start = text.index("def enqueue_webhook_delivery")
    chunk = text[start : start + 1400]

    assert "lease_expires_at" in chunk
    assert "now() + make_interval(secs => %s)" in chunk
    assert "_claim_lease_seconds" in chunk
    assert "ON CONFLICT (webhook_id, event_id) DO NOTHING" in chunk
    # Winner-only inline delivery still depends on rowcount.
    assert "rowcount" in chunk
