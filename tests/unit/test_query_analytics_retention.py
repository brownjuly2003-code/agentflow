"""Query analytics keeps a fingerprint, not the question (audit F-18).

`/v1/query` takes free text. The analytics middleware persisted the first 1000
characters of it verbatim, forever, and the admin top-queries surface read it
back. Truncation bounds size; it says nothing about sensitivity or lifetime,
and users type PII, commercial figures and the occasional pasted credential.

Three properties are pinned here: the default record carries no question, an
operator who opts in gets a redacted one rather than a raw one, and retention
is a finite window something can actually enforce.
"""

from __future__ import annotations

import duckdb
import pytest

from agentflow_runtime.serving.api.query_analytics_policy import (
    DEFAULT_FINGERPRINT_PEPPER,
    DEFAULT_RETENTION_DAYS,
    QueryAnalyticsPolicy,
    QueryAnalyticsPolicyError,
)
from agentflow_runtime.serving.control_plane import (
    EmbeddedControlPlaneStore,
    ensure_api_sessions_table,
)


def _store(usage_db) -> EmbeddedControlPlaneStore:
    """A store whose analytics table exists.

    `record_api_session` deliberately does not create it on the hot path -- the
    API's boot does that once -- so a test that only calls `ensure_usage_schema`
    would write into a database with no `api_sessions`.
    """
    conn = duckdb.connect(str(usage_db))
    try:
        ensure_api_sessions_table(conn)
    finally:
        conn.close()
    return EmbeddedControlPlaneStore(usage_db_path_provider=lambda: usage_db)


def _record(**overrides) -> dict:
    record = {
        "tenant": "acme",
        "key_name": "support",
        "endpoint": "/v1/query",
        "method": "POST",
        "status_code": 200,
        "duration_ms": 4.2,
        "cache_hit": False,
        "entity_type": None,
        "entity_id": None,
        "metric_name": None,
        "query_engine": "rule_based",
        "query_text": None,
        "query_fingerprint": None,
    }
    record.update(overrides)
    return record


# --- policy ------------------------------------------------------------------


def test_the_default_policy_stores_no_question_text():
    text, fingerprint = QueryAnalyticsPolicy().capture("what was revenue last quarter?")

    assert text is None
    assert len(fingerprint) == 64


def test_opting_in_stores_a_redacted_question_never_a_raw_one():
    policy = QueryAnalyticsPolicy(store_query_text=True)

    text, _ = policy.capture(
        "email jane.doe@example.com about api_key=sk-live-9f8e7d6c5b4a and card 4111 1111 1111 1111"
    )

    assert text is not None
    assert "jane.doe@example.com" not in text
    assert "sk-live-9f8e7d6c5b4a" not in text
    assert "4111 1111 1111 1111" not in text
    assert "[email]" in text
    assert "[secret]" in text
    assert "[number]" in text


def test_a_jwt_is_redacted():
    policy = QueryAnalyticsPolicy(store_query_text=True)
    # A structurally valid JWT of no value to anyone: the RFC 7519 example
    # header/payload with a truncated signature.
    jwt_sample = (  # noqa: S105 - sample token, not a credential
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
    )

    text, _ = policy.capture(f"why did {jwt_sample} stop working?")

    assert jwt_sample not in (text or "")
    assert "[jwt]" in (text or "")


def test_ordinary_questions_survive_redaction_intact():
    """Redaction that mangles every question would make the opt-in useless."""
    policy = QueryAnalyticsPolicy(store_query_text=True)
    question = "which product had the highest conversion rate in Q3 2026?"

    text, _ = policy.capture(question)

    assert text == question


def test_opted_in_text_is_still_truncated():
    policy = QueryAnalyticsPolicy(store_query_text=True, max_query_text_chars=50)

    text, _ = policy.capture("x" * 5000)

    assert text is not None
    assert len(text) == 50


def test_the_fingerprint_ignores_case_and_spacing_but_not_content():
    policy = QueryAnalyticsPolicy()

    assert policy.fingerprint("What  was REVENUE?") == policy.fingerprint("what was revenue?")
    assert policy.fingerprint("what was revenue?") != policy.fingerprint("what was churn?")


def test_the_fingerprint_is_peppered():
    """A leaked analytics table must not join against fingerprints of the same
    questions computed elsewhere -- the key-lookup pepper's reasoning."""
    question = "what was revenue last quarter?"
    default = QueryAnalyticsPolicy().fingerprint(question)
    other = QueryAnalyticsPolicy(fingerprint_pepper="different").fingerprint(question)

    assert default != other


def test_the_fingerprint_is_computed_from_the_question_not_the_redaction():
    """Fingerprinting the redacted form would merge every question that differs
    only inside a redacted span."""
    policy = QueryAnalyticsPolicy(store_query_text=True)

    _, first = policy.capture("orders for a@example.com")
    _, second = policy.capture("orders for b@example.com")

    assert first != second


# --- configuration -----------------------------------------------------------


def test_from_env_defaults_to_fingerprint_only_with_a_finite_window():
    policy = QueryAnalyticsPolicy.from_env({})

    assert policy.store_query_text is False
    assert policy.retention_days == DEFAULT_RETENTION_DAYS


def test_production_refuses_to_boot_without_an_operator_pepper():
    """AF-13: the default pepper is committed to the repo, so on production it
    protects nothing. Fail at boot, not after the first leaked table."""
    with pytest.raises(QueryAnalyticsPolicyError, match="AGENTFLOW_QUERY_FINGERPRINT_PEPPER"):
        QueryAnalyticsPolicy.from_env({"AGENTFLOW_PROFILE": "production"})


def test_production_refuses_the_default_pepper_even_when_set_explicitly():
    with pytest.raises(QueryAnalyticsPolicyError, match="built-in default"):
        QueryAnalyticsPolicy.from_env(
            {
                "AGENTFLOW_PROFILE": "production",
                "AGENTFLOW_QUERY_FINGERPRINT_PEPPER": DEFAULT_FINGERPRINT_PEPPER,
            }
        )


def test_production_accepts_an_operator_pepper():
    policy = QueryAnalyticsPolicy.from_env(
        {"AGENTFLOW_PROFILE": "production", "AGENTFLOW_QUERY_FINGERPRINT_PEPPER": " s3cret "}
    )
    assert policy.fingerprint_pepper == "s3cret"


@pytest.mark.parametrize("profile", ["", "dev", "demo"])
def test_non_production_profiles_keep_the_default_pepper(profile: str):
    env = {"AGENTFLOW_PROFILE": profile} if profile else {}
    assert QueryAnalyticsPolicy.from_env(env).fingerprint_pepper == DEFAULT_FINGERPRINT_PEPPER


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_store_text_opt_in_accepts_the_usual_true_spellings(value: str):
    policy = QueryAnalyticsPolicy.from_env({"AGENTFLOW_QUERY_ANALYTICS_STORE_TEXT": value})

    assert policy.store_query_text is True


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_store_text_stays_off_for_false_spellings(value: str):
    policy = QueryAnalyticsPolicy.from_env({"AGENTFLOW_QUERY_ANALYTICS_STORE_TEXT": value})

    assert policy.store_query_text is False


def test_an_unparseable_opt_in_is_refused_rather_than_guessed():
    with pytest.raises(QueryAnalyticsPolicyError, match="not a boolean"):
        QueryAnalyticsPolicy.from_env({"AGENTFLOW_QUERY_ANALYTICS_STORE_TEXT": "sometimes"})


def test_an_unparseable_retention_window_is_refused():
    """A typo must not quietly mean "keep questions forever"."""
    with pytest.raises(QueryAnalyticsPolicyError, match="whole number of days"):
        QueryAnalyticsPolicy.from_env({"AGENTFLOW_QUERY_ANALYTICS_RETENTION_DAYS": "30d"})


@pytest.mark.parametrize("days", [0, -1])
def test_retention_must_be_at_least_a_day(days: int):
    with pytest.raises(QueryAnalyticsPolicyError, match="at least 1 day"):
        QueryAnalyticsPolicy(retention_days=days)


# --- the embedded store ------------------------------------------------------


def test_top_queries_reports_repeats_by_fingerprint_when_no_text_is_stored(tmp_path):
    """Grouping by `query_text` alone would report "no queries" for a busy API
    the moment the default policy stopped storing text."""
    store = _store(tmp_path / "usage.duckdb")
    policy = QueryAnalyticsPolicy()
    _, digest = policy.capture("what was revenue?")

    for index in range(3):
        store.record_api_session(f"req-{index}", _record(query_fingerprint=digest, query_text=None))
    store.record_api_session(
        "req-other", _record(query_fingerprint=policy.fingerprint("what was churn?"))
    )

    top = store.get_top_queries(limit=5)

    assert top["queries"][0] == {"query": None, "fingerprint": digest, "count": 3}
    assert len(top["queries"]) == 2


def test_top_queries_still_shows_text_when_the_operator_opted_in(tmp_path):
    store = _store(tmp_path / "usage.duckdb")
    policy = QueryAnalyticsPolicy(store_query_text=True)
    text, digest = policy.capture("what was revenue?")

    store.record_api_session("req-1", _record(query_text=text, query_fingerprint=digest))

    top = store.get_top_queries(limit=5)

    assert top["queries"] == [{"query": "what was revenue?", "fingerprint": digest, "count": 1}]


def test_pruning_deletes_rows_past_the_window_and_keeps_the_rest(tmp_path):
    usage_db = tmp_path / "usage.duckdb"
    store = _store(usage_db)
    store.record_api_session("old", _record(query_fingerprint="a" * 64))
    store.record_api_session("fresh", _record(query_fingerprint="b" * 64))

    conn = duckdb.connect(str(usage_db))
    try:
        conn.execute(
            "UPDATE api_sessions SET ts = CURRENT_TIMESTAMP - INTERVAL 90 DAY "
            "WHERE request_id = 'old'"
        )
    finally:
        conn.close()

    deleted = store.prune_api_sessions(older_than_days=30)

    conn = duckdb.connect(str(usage_db))
    try:
        remaining = [
            row[0] for row in conn.execute("SELECT request_id FROM api_sessions").fetchall()
        ]
    finally:
        conn.close()

    assert deleted == 1
    assert remaining == ["fresh"]


def test_pruning_is_idempotent(tmp_path):
    store = _store(tmp_path / "usage.duckdb")
    store.record_api_session("fresh", _record(query_fingerprint="c" * 64))

    assert store.prune_api_sessions(older_than_days=30) == 0
    assert store.prune_api_sessions(older_than_days=30) == 0


def test_pruning_refuses_a_zero_day_window(tmp_path):
    """`older_than_days=0` reads as "delete everything now", which is a
    different operation than enforcing retention and must be asked for
    explicitly, not by passing a falsy default."""
    store = _store(tmp_path / "usage.duckdb")

    with pytest.raises(ValueError, match="at least 1"):
        store.prune_api_sessions(older_than_days=0)


# --- the prune job -----------------------------------------------------------


def test_prune_script_reports_what_it_deleted(capsys, tmp_path):
    from scripts.prune_query_analytics import main

    class _Store:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def prune_api_sessions(self, *, older_than_days: int) -> int:
            self.calls.append(older_than_days)
            return 7

    store = _Store()
    code = main(["--retention-days", "14"], store=store)

    assert code == 0
    assert store.calls == [14]
    assert "pruned 7 api_sessions rows older than 14d" in capsys.readouterr().out


def test_prune_script_dry_run_deletes_nothing(capsys):
    from scripts.prune_query_analytics import main

    class _Store:
        def prune_api_sessions(self, *, older_than_days: int) -> int:  # pragma: no cover
            raise AssertionError("a dry run must not delete")

    code = main(["--dry-run"], store=_Store())

    assert code == 0
    assert "dry run" in capsys.readouterr().out


def test_prune_script_refuses_a_zero_retention_window():
    from scripts.prune_query_analytics import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--retention-days", "0"])


# --- tenant-scoped erasure ---------------------------------------------------


def test_erasing_a_tenant_removes_its_rows_at_any_age_and_spares_the_others(tmp_path):
    """A tenant asking for their analytics to go does not wait out the window,
    and their neighbour's rows are not collateral."""
    usage_db = tmp_path / "usage.duckdb"
    store = _store(usage_db)
    store.record_api_session("acme-old", _record(query_fingerprint="d" * 64))
    store.record_api_session("acme-fresh", _record(query_fingerprint="e" * 64))
    store.record_api_session("other", _record(tenant="globex", query_fingerprint="f" * 64))

    conn = duckdb.connect(str(usage_db))
    try:
        conn.execute(
            "UPDATE api_sessions SET ts = CURRENT_TIMESTAMP - INTERVAL 90 DAY "
            "WHERE request_id = 'acme-old'"
        )
    finally:
        conn.close()

    deleted = store.delete_tenant_api_sessions(tenant="acme")

    conn = duckdb.connect(str(usage_db))
    try:
        remaining = [
            row[0] for row in conn.execute("SELECT request_id FROM api_sessions").fetchall()
        ]
    finally:
        conn.close()

    assert deleted == 2
    assert remaining == ["other"]


def test_erasing_an_unknown_tenant_is_a_no_op(tmp_path):
    store = _store(tmp_path / "usage.duckdb")
    store.record_api_session("kept", _record(query_fingerprint="a" * 64))

    assert store.delete_tenant_api_sessions(tenant="never-seen") == 0


def test_erasure_refuses_an_empty_tenant(tmp_path):
    """An empty identifier would delete every tenant's rows, which is not what
    an erasure request means."""
    store = _store(tmp_path / "usage.duckdb")

    with pytest.raises(ValueError, match="non-empty"):
        store.delete_tenant_api_sessions(tenant="")


def test_erase_script_reports_what_it_deleted(capsys):
    from scripts.prune_query_analytics import main

    class _Store:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def delete_tenant_api_sessions(self, *, tenant: str) -> int:
            self.calls.append(tenant)
            return 3

        def prune_api_sessions(self, *, older_than_days: int) -> int:  # pragma: no cover
            raise AssertionError("an erasure request must not prune by window")

    store = _Store()
    code = main(["--erase-tenant", "acme"], store=store)

    assert code == 0
    assert store.calls == ["acme"]
    assert "erased 3 api_sessions rows for tenant 'acme'" in capsys.readouterr().out


def test_erase_script_dry_run_deletes_nothing(capsys):
    from scripts.prune_query_analytics import main

    class _Store:
        def delete_tenant_api_sessions(self, *, tenant: str) -> int:  # pragma: no cover
            raise AssertionError("a dry run must not delete")

    code = main(["--erase-tenant", "acme", "--dry-run"], store=_Store())

    assert code == 0
    assert "dry run" in capsys.readouterr().out


def test_erasure_and_a_retention_window_are_not_combined():
    """Two different deletions; passing both is ambiguous, so the script
    refuses instead of silently picking one."""
    from scripts.prune_query_analytics import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--erase-tenant", "acme", "--retention-days", "7"])


def test_erasure_refuses_a_blank_tenant_identifier():
    from scripts.prune_query_analytics import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--erase-tenant", "   "])
