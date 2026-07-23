from datetime import UTC, datetime

from src.processing.flink_jobs.checkpointing import configure_checkpointing
from src.processing.flink_jobs.session_window import (
    accumulate_session,
    new_session,
    session_key,
    summarize_session,
)

BASE_TIME = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)
BASE_TIME_MS = int(BASE_TIME.timestamp() * 1000)


def _event(
    *,
    tenant: str = "acme",
    session_id: str = "session-1",
    user_id: str = "user-1",
    page_url: str = "/home",
    product_id: str | None = None,
) -> dict:
    return {
        "tenant": tenant,
        "session_id": session_id,
        "user_id": user_id,
        "event_type": "page_view",
        "page_url": page_url,
        "product_id": product_id,
    }


def test_session_opens_on_first_event():
    session = new_session(_event(), BASE_TIME_MS)

    assert session["tenant_id"] == "acme"
    assert session["session_id"] == "session-1"
    assert session["event_count"] == 0
    assert session["pages"] == []


def test_session_updates_within_gap():
    session = new_session(_event(page_url="/one"), BASE_TIME_MS)
    accumulate_session(
        session,
        _event(page_url="/one"),
        BASE_TIME_MS,
        max_unique_pages=10,
        max_unique_products=10,
    )
    accumulate_session(
        session,
        _event(page_url="/two"),
        BASE_TIME_MS + 60_000,
        max_unique_pages=10,
        max_unique_products=10,
    )

    assert session["event_count"] == 2
    assert session["pages"] == ["/one", "/two"]


def test_out_of_order_event_preserves_latest_session_end():
    session = new_session(_event(), BASE_TIME_MS + 60_000)
    accumulate_session(
        session,
        _event(page_url="/later"),
        BASE_TIME_MS + 60_000,
        max_unique_pages=10,
        max_unique_products=10,
    )
    accumulate_session(
        session,
        _event(page_url="/earlier"),
        BASE_TIME_MS,
        max_unique_pages=10,
        max_unique_products=10,
    )

    assert session["first_event_ts"] == BASE_TIME_MS
    assert session["last_event_ts"] == BASE_TIME_MS + 60_000


def test_session_collections_are_bounded_and_visible_in_summary():
    session = new_session(_event(), BASE_TIME_MS)
    for offset, (page, product) in enumerate(
        [("/one", "sku-1"), ("/two", "sku-2"), ("/three", "sku-3")]
    ):
        accumulate_session(
            session,
            _event(page_url=page, product_id=product),
            BASE_TIME_MS + offset,
            max_unique_pages=2,
            max_unique_products=1,
        )

    summary = summarize_session(session)

    assert summary["unique_pages"] == 2
    assert summary["products_viewed"] == 1
    assert summary["pages_truncated"] is True
    assert summary["products_truncated"] is True


def test_same_session_id_is_isolated_per_tenant():
    assert session_key(_event(tenant="acme")) == "acme\x1fsession-1"
    assert session_key(_event(tenant="globex")) == "globex\x1fsession-1"


def test_legacy_tenant_id_remains_compatible():
    event = _event()
    event["tenant_id"] = event.pop("tenant")

    assert session_key(event) == "acme\x1fsession-1"


class _FakeCheckpointConfig:
    def __init__(self):
        self.mode = None
        self.min_pause = None
        self.timeout = None
        self.max_concurrent = None
        self.retention = None

    def set_checkpointing_mode(self, value):
        self.mode = value

    def set_min_pause_between_checkpoints(self, value):
        self.min_pause = value

    def set_checkpoint_timeout(self, value):
        self.timeout = value

    def set_max_concurrent_checkpoints(self, value):
        self.max_concurrent = value

    def set_externalized_checkpoint_retention(self, value):
        self.retention = value


class _FakeEnv:
    def __init__(self):
        self.interval = None
        self.config = _FakeCheckpointConfig()
        self.configured = None

    def enable_checkpointing(self, value):
        self.interval = value

    def get_checkpoint_config(self):
        return self.config

    def configure(self, configuration):
        self.configured = configuration


def test_checkpointing_configuration_uses_exactly_once(monkeypatch):
    env = _FakeEnv()
    monkeypatch.setenv("FLINK_CHECKPOINT_DIR", "file:///var/lib/flink-checkpoints")

    configure_checkpointing(env)

    assert env.interval == 60_000
    assert env.config.mode == "EXACTLY_ONCE"
    assert env.config.min_pause == 30_000
    assert env.config.timeout == 120_000
    assert env.config.max_concurrent == 1
    assert env.config.retention == "RETAIN_ON_CANCELLATION"
    assert env.configured == {"execution.checkpointing.dir": "file:///var/lib/flink-checkpoints"}


def test_checkpointing_configuration_defaults_to_tmp_directory(monkeypatch):
    env = _FakeEnv()
    monkeypatch.delenv("FLINK_CHECKPOINT_DIR", raising=False)

    configure_checkpointing(env)

    assert env.configured == {"execution.checkpointing.dir": "file:///tmp/flink-checkpoints"}
