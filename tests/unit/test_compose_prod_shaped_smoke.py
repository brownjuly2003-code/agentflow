"""The compose smoke script's own contract (audit F-09).

The point of the script is that a 503 on an anonymous read is a *failure*, not
a pass. Fail-closed for want of an auth contract looks identical to fail-closed
because the caller had no key -- and the first one is exactly the defect the
stack shipped with, so the distinction is the whole test surface here.
"""

from urllib.error import HTTPError, URLError

import pytest

from scripts.compose_prod_shaped_smoke import main, parse_args, run_smoke


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _opener(routes: dict[tuple[str, str | None], int | Exception]):
    """Answer by (path, api key) so a test can distinguish the two /v1 calls."""

    def open_(request, timeout):  # noqa: ANN001 - urlopen's shape
        path = request.full_url.split("localhost:8000", 1)[-1]
        key = request.get_header("X-api-key")
        answer = routes[(path, key)]
        if isinstance(answer, Exception):
            raise answer
        if answer >= 400:
            raise HTTPError(request.full_url, answer, "refused", {}, None)  # type: ignore[arg-type]
        return _Response(answer)

    return open_


def _healthy_routes(anonymous: int = 401, authenticated: int = 200) -> dict:
    return {
        ("/health/ready", None): 200,
        ("/v1/catalog", None): anonymous,
        ("/v1/catalog", "demo-key"): authenticated,
    }


def test_all_three_checks_pass_against_a_correctly_wired_stack():
    results = run_smoke(opener=_opener(_healthy_routes()))

    assert [result.name for result in results] == [
        "readiness",
        "anonymous_refused",
        "authenticated_read",
    ]
    assert all(result.ok for result in results)


def test_anonymous_503_fails_and_names_the_missing_auth_contract():
    """The regression this script exists for: the stack loaded no keys, so
    every route was refused and a naive check would call that fail-closed."""
    results = run_smoke(opener=_opener(_healthy_routes(anonymous=503)))
    anonymous = next(result for result in results if result.name == "anonymous_refused")

    assert not anonymous.ok
    assert "no API keys" in anonymous.detail
    assert "do not treat this as a passing fail-closed check" in anonymous.detail


def test_anonymous_200_fails_because_the_route_is_unauthenticated():
    results = run_smoke(opener=_opener(_healthy_routes(anonymous=200)))
    anonymous = next(result for result in results if result.name == "anonymous_refused")

    assert not anonymous.ok


def test_authenticated_refusal_fails():
    results = run_smoke(opener=_opener(_healthy_routes(authenticated=401)))
    authenticated = next(result for result in results if result.name == "authenticated_read")

    assert not authenticated.ok


def test_transport_failure_is_reported_not_raised():
    routes = _healthy_routes()
    routes[("/health/ready", None)] = URLError("connection refused")
    results = run_smoke(opener=_opener(routes))
    readiness = next(result for result in results if result.name == "readiness")

    assert not readiness.ok
    assert "no response" in readiness.detail


def test_base_url_trailing_slash_does_not_double_up_the_path():
    results = run_smoke(base_url="http://localhost:8000/", opener=_opener(_healthy_routes()))

    assert all(result.ok for result in results)


def test_main_exit_code_follows_the_checks(capsys, monkeypatch):
    from scripts import compose_prod_shaped_smoke

    monkeypatch.setattr(
        compose_prod_shaped_smoke,
        "urlopen",
        _opener(_healthy_routes(authenticated=503)),
    )

    code = main([])

    output = capsys.readouterr().out
    assert code == 1
    # The other two checks passed through the substitute opener, which proves
    # main() actually used it instead of reaching the network.
    assert "[PASS] readiness" in output
    assert "[PASS] anonymous_refused" in output
    assert "[FAIL] authenticated_read" in output
    assert "smoke FAILED" in output


def test_parse_args_rejects_an_empty_key_and_a_nonpositive_timeout():
    with pytest.raises(SystemExit):
        parse_args(["--api-key", ""])
    with pytest.raises(SystemExit):
        parse_args(["--timeout", "0"])


def test_a_non_http_target_is_refused_by_both_entry_points():
    """urllib opens `file:` as readily as http, and the target comes from the
    command line."""
    with pytest.raises(SystemExit):
        parse_args(["--base-url", "file:///etc/passwd"])
    with pytest.raises(ValueError, match="http"):
        run_smoke(base_url="file:///etc/passwd", opener=_opener({}))
