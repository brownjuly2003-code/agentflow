"""Every refusal on the admin surface leaves an audit line (audit FB-10).

``require_admin_key`` guards the routes that issue, rotate and revoke every
tenant key. It counted its refusals in ``AUTH_FAILURES{reason=...}`` and wrote
nothing else. A counter says an admin refusal happened somewhere in the
deployment; it cannot say from which address, against which route, or whether
the 503 that woke someone at 03:00 was a Secret rotated without the Deployment
picking it up -- the incident ``docs/runbooks/auth-401-spike.md`` describes.
Meanwhile the tenant path has logged ``api_auth_failed`` since audit F-11, so
the highest-privilege credential in the system was the one surface with no
audit trail.

Two properties are pinned here. Every branch that counts a refusal also emits
``admin_auth_failed`` -- structurally, so a fourth branch cannot be added with
a counter alone. And the line never carries the credential that was tried,
even when the operator's own redaction policy has been narrowed to nothing:
``sensitive_headers_to_redact`` is operator-configurable, and F-11 already had
to repair a built-in default that omitted ``X-Admin-Key``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import structlog
import yaml
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from agentflow_runtime.serving.api.auth import AuthManager, build_auth_middleware
from agentflow_runtime.serving.api.auth import middleware as middleware_module
from agentflow_runtime.serving.api.auth.middleware import require_admin_key
from agentflow_runtime.serving.api.security import compute_key_lookup, hash_api_key

ADMIN_KEY = "admin-secret-value"
TENANT_KEY = "tenant-order-key"
WRONG_ADMIN_KEY = "not-the-admin-key"
FAILED_AUTH_LIMIT = 2
BCRYPT_TEST_ROUNDS = 4

ADMIN_EVENT = "admin_auth_failed"
TENANT_EVENT = "api_auth_failed"
ADMIN_PATH = "/v1/admin/ping"
TENANT_PATH = "/v1/metrics/revenue"

# The peer address every TestClient request arrives from.
PEER = "testclient"

# The full redaction policy `config/security.yaml` ships.
CANONICAL_REDACTION = ["Authorization", "X-API-Key", "X-Admin-Key", "Cookie", "Set-Cookie"]


def _write_config(tmp_path: Path, *, redact: list[str]) -> tuple[Path, Path]:
    keys_path = tmp_path / "config" / "api_keys.yaml"
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "key_id": "key-indexed",
                        "key_hash": hash_api_key(
                            TENANT_KEY, rounds=BCRYPT_TEST_ROUNDS, scheme="argon2id"
                        ),
                        "key_lookup": compute_key_lookup(TENANT_KEY),
                        "name": "indexed",
                        "tenant": "acme",
                        "rate_limit_rpm": 120,
                        "created_at": "2026-09-07",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    security_path = tmp_path / "config" / "security.yaml"
    security_path.write_text(
        yaml.safe_dump(
            {
                "security": {
                    "key_hashing": "argon2id",
                    "bcrypt_rounds": BCRYPT_TEST_ROUNDS,
                    "min_key_length": 8,
                    "max_failed_auth_per_ip_per_hour": FAILED_AUTH_LIMIT,
                    "sensitive_headers_to_redact": redact,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return keys_path, security_path


def _build_client(
    tmp_path: Path,
    *,
    admin_key: str | None = ADMIN_KEY,
    redact: list[str] | None = None,
) -> TestClient:
    keys_path, security_path = _write_config(
        tmp_path, redact=CANONICAL_REDACTION if redact is None else redact
    )
    application = FastAPI()
    application.state.auth_manager = AuthManager(
        api_keys_path=keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key=admin_key,
        security_config_path=security_path,
    )
    application.state.auth_manager.load()
    application.state.auth_manager.ensure_usage_table()
    application.middleware("http")(build_auth_middleware())

    @application.get(TENANT_PATH)
    async def revenue() -> dict[str, int]:
        return {"revenue": 1}

    # AuthMiddleware hands /v1/admin* straight to the route, so the admin
    # dependency is the only thing standing in front of this one.
    admin = APIRouter(dependencies=[Depends(require_admin_key)])

    @admin.get(ADMIN_PATH)
    async def admin_ping() -> dict[str, bool]:
        return {"ok": True}

    application.include_router(admin)
    return TestClient(application)


@pytest.fixture(autouse=True)
def _no_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """No proxy is trusted unless the test says so, so `client_ip` is the peer."""
    monkeypatch.delenv("AGENTFLOW_TRUSTED_PROXIES", raising=False)


@pytest.fixture(autouse=True)
def _uncached_auth_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-point the auth package logger at a fresh, uncached proxy.

    Any earlier test that imports ``agentflow_runtime.serving.api.main`` runs
    ``configure_logging()`` (``cache_logger_on_first_use=True``); the first
    emit through the module-level auth logger then freezes the production
    processor chain onto the proxy and ``structlog.testing.capture_logs()``
    goes blind -- the warning still emits, so the file would pass under
    ``tests/unit`` alone and fail in a full-repo run. Binding a fresh proxy
    keeps these tests order-independent (the same fix as
    ``test_auth_hashed_key_guidance.py``).
    """
    from agentflow_runtime.serving.api import auth as auth_package

    monkeypatch.setattr(auth_package, "logger", structlog.get_logger())


def _admin_lines(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("event") == ADMIN_EVENT]


def test_an_invalid_admin_key_leaves_one_audit_line(tmp_path: Path) -> None:
    """The refusal an operator needs to see: someone is guessing the key that
    issues every tenant key, and this says from where and against what."""
    client = _build_client(tmp_path)

    with structlog.testing.capture_logs() as events:
        response = client.get(ADMIN_PATH, headers={"X-Admin-Key": WRONG_ADMIN_KEY})

    assert response.status_code == 401
    lines = _admin_lines(events)
    assert len(lines) == 1, f"expected exactly one {ADMIN_EVENT} line, got {events}"
    line = lines[0]
    assert line["reason"] == "admin_invalid"
    assert line["client_ip"] == PEER
    assert line["path"] == ADMIN_PATH
    assert line["log_level"] == "warning"


def test_a_request_with_no_admin_header_is_audited_the_same_way(tmp_path: Path) -> None:
    """A missing header and a wrong value are one branch in the code and one
    incident in practice -- a scanner sends both."""
    client = _build_client(tmp_path)

    with structlog.testing.capture_logs() as events:
        response = client.get(ADMIN_PATH)

    assert response.status_code == 401
    assert [line["reason"] for line in _admin_lines(events)] == ["admin_invalid"]


def test_the_throttled_refusal_is_audited_as_rate_limited(tmp_path: Path) -> None:
    """Once the window trips, the 429s are the only record that the guessing
    continued. Losing them would hide the tail of an attack behind the brake
    installed to slow it down."""
    client = _build_client(tmp_path)

    with structlog.testing.capture_logs() as events:
        for _ in range(FAILED_AUTH_LIMIT + 3):
            response = client.get(ADMIN_PATH, headers={"X-Admin-Key": WRONG_ADMIN_KEY})
            if response.status_code == 429:
                break
        else:
            raise AssertionError(
                f"the admin throttle never tripped at a limit of {FAILED_AUTH_LIMIT}"
            )

    reasons = [line["reason"] for line in _admin_lines(events)]
    assert reasons[-1] == "rate_limited"
    assert reasons[:-1] == ["admin_invalid"] * (len(reasons) - 1)


def test_an_unconfigured_admin_key_is_audited_and_not_only_counted(tmp_path: Path) -> None:
    """This is the 503 in the runbook's "Admin key revoked or rotated
    incorrectly" section. With only a counter, the operator's evidence that the
    Deployment never picked up the rotated Secret was a number going up."""
    client = _build_client(tmp_path, admin_key=None)

    with structlog.testing.capture_logs() as events:
        response = client.get(ADMIN_PATH, headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 503
    assert [line["reason"] for line in _admin_lines(events)] == ["admin_unconfigured"]


def test_a_valid_admin_key_leaves_no_audit_line(tmp_path: Path) -> None:
    """An audit line on success would bury the refusals in routine traffic --
    the retention CronJob calls this surface on a schedule."""
    client = _build_client(tmp_path)

    with structlog.testing.capture_logs() as events:
        response = client.get(ADMIN_PATH, headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 200
    assert _admin_lines(events) == []


@pytest.mark.parametrize(
    ("redact", "case"),
    [
        (CANONICAL_REDACTION, "the shipped policy"),
        ([], "a policy narrowed to nothing"),
        (["Authorization"], "a policy that forgot the admin header"),
    ],
)
def test_the_audit_line_never_carries_the_key_that_was_tried(
    tmp_path: Path, redact: list[str], case: str
) -> None:
    """`sensitive_headers_to_redact` belongs to the operator, and F-11 had to
    repair a built-in default that omitted `X-Admin-Key`. On the one credential
    every operator shares, the audit line drops the header itself rather than
    trusting that list to be right."""
    client = _build_client(tmp_path, redact=redact)

    with structlog.testing.capture_logs() as events:
        client.get(ADMIN_PATH, headers={"X-Admin-Key": WRONG_ADMIN_KEY})

    lines = _admin_lines(events)
    assert len(lines) == 1
    headers = lines[0]["headers"]
    assert headers["x-admin-key"] == "[REDACTED]", f"admin key survived {case}"
    assert WRONG_ADMIN_KEY not in repr(lines[0])


def test_the_audit_line_still_carries_what_incident_response_needs(tmp_path: Path) -> None:
    """Dropping the credential is not the same as dropping the headers: the
    forwarded-for chain and user-agent are how a scan gets attributed."""
    client = _build_client(tmp_path)

    with structlog.testing.capture_logs() as events:
        client.get(
            ADMIN_PATH,
            headers={
                "X-Admin-Key": WRONG_ADMIN_KEY,
                "User-Agent": "curl/8.7.1",
                "X-Forwarded-For": "203.0.113.7",
            },
        )

    headers = _admin_lines(events)[0]["headers"]
    assert headers["user-agent"] == "curl/8.7.1"
    assert headers["x-forwarded-for"] == "203.0.113.7"


def test_the_admin_event_is_distinct_from_the_tenant_event(tmp_path: Path) -> None:
    """A scan against /v1 and someone guessing the operator key are different
    incidents. One event name for both would make the admin signal a needle in
    whatever volume the tenant surface is taking."""
    client = _build_client(tmp_path)

    with structlog.testing.capture_logs() as events:
        assert client.get(TENANT_PATH, headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get(ADMIN_PATH, headers={"X-Admin-Key": WRONG_ADMIN_KEY}).status_code == 401

    names = [event.get("event") for event in events]
    assert names.count(TENANT_EVENT) == 1
    assert names.count(ADMIN_EVENT) == 1


def _require_admin_key_node() -> ast.FunctionDef:
    source = Path(middleware_module.__file__).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "require_admin_key":
            return node
    raise AssertionError("require_admin_key is no longer a module-level function")


def _reasons_by_callee(node: ast.FunctionDef) -> dict[str, set[str]]:
    """``{callee: {reason literals it is called with}}`` inside one function."""
    found: dict[str, set[str]] = {}
    for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
        reason = next(
            (
                keyword.value.value
                for keyword in call.keywords
                if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant)
            ),
            None,
        )
        if reason is None:
            continue
        found.setdefault(ast.unparse(call.func), set()).add(reason)
    return found


def test_every_counted_admin_refusal_is_also_audited() -> None:
    """The ratchet. The regression FB-10 found was not a wrong log line, it was
    a branch that incremented a counter and returned; reading the source keeps
    a fourth branch from being added the same way."""
    reasons = _reasons_by_callee(_require_admin_key_node())
    counted = reasons.get("AUTH_FAILURES.labels", set())
    logged = reasons.get("_log_admin_auth_failed", set())

    assert counted == {"admin_unconfigured", "admin_invalid", "rate_limited"}
    assert logged == counted, (
        f"admin refusals counted but never audited: {sorted(counted - logged)}; "
        f"audited but never counted: {sorted(logged - counted)}"
    )


# `metrics.py` points at the runbook's Detection section for the `reason` label
# vocabulary, which makes that section the only place an operator can look up
# what a counter value means.
RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "auth-401-spike.md"
DETECTION_HEADING = "## Detection"

# Documented for months; no call site ever emitted it. Removed with FB-10, and
# named here so it cannot drift back in beside a label that is real.
RETIRED_REASONS = {"disabled_key"}


def _emitted_reasons() -> set[str]:
    """Every `reason` label value the middleware can hand to `AUTH_FAILURES`.

    Three of them reach the counter through a local variable in the tenant
    branch, so reading the call sites alone would miss them.
    """
    tree = ast.parse(Path(middleware_module.__file__).read_text(encoding="utf-8"))
    reasons: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "AUTH_FAILURES.labels":
            reasons |= {
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant)
            }
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and any(
                isinstance(target, ast.Name) and target.id == "reason" for target in node.targets
            )
        ):
            reasons.add(node.value.value)
    return reasons


def _detection_section() -> str:
    lines = RUNBOOK.read_text(encoding="utf-8").splitlines()
    start = lines.index(DETECTION_HEADING)
    end = next(
        (
            offset
            for offset, line in enumerate(lines[start + 1 :], start + 1)
            if line.startswith("## ")
        ),
        len(lines),
    )
    return " ".join(lines[start:end])


def test_the_runbook_names_every_reason_label_the_code_emits() -> None:
    """The operator-visibility half of FB-10. A counter an on-call engineer
    cannot look up is barely better than no counter, and the Detection list was
    wrong in both directions: it carried `disabled_key`, which no call site
    emits, and neither admin reason -- the pair someone paging on an admin
    refusal actually needed."""
    detection = _detection_section()
    emitted = _emitted_reasons()

    assert emitted == {
        "key_file_empty",
        "missing_key",
        "invalid_key",
        "rate_limited",
        "admin_unconfigured",
        "admin_invalid",
    }
    undocumented = sorted(reason for reason in emitted if f"`{reason}`" not in detection)
    assert undocumented == [], (
        f"{RUNBOOK.name} Detection section does not name these emitted labels: {undocumented}"
    )
    stale = sorted(reason for reason in RETIRED_REASONS if f"`{reason}`" in detection)
    assert stale == [], f"{RUNBOOK.name} still documents labels nothing emits: {stale}"
