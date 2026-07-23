from __future__ import annotations

from urllib.error import URLError

import pytest

from scripts.wait_for_http import wait_for_http


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_wait_for_http_retries_until_success() -> None:
    outcomes: list[Exception | _Response] = [
        URLError("not ready"),
        _Response(503),
        _Response(200),
    ]
    sleeps: list[float] = []

    def opener(url: str, timeout: float) -> _Response:
        assert url == "http://service/health"
        assert timeout > 0
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    ready = wait_for_http(
        url="http://service/health",
        timeout=10,
        interval=0.25,
        label="test service",
        opener=opener,
        monotonic=iter((0.0, 0.1, 0.2, 0.3, 0.4, 0.5)).__next__,
        sleep=sleeps.append,
    )

    assert ready is True
    assert sleeps == [0.25, 0.25]


def test_wait_for_http_stops_at_deadline() -> None:
    attempts = 0

    def opener(url: str, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        raise URLError("still unavailable")

    ready = wait_for_http(
        url="http://service/health",
        timeout=1,
        interval=0.5,
        label="test service",
        opener=opener,
        monotonic=iter((0.0, 0.2, 1.0)).__next__,
        sleep=lambda seconds: None,
    )

    assert ready is False
    assert attempts == 1


def test_wait_for_http_caps_each_request_at_remaining_deadline() -> None:
    request_timeouts: list[float] = []

    def opener(url: str, timeout: float) -> _Response:
        request_timeouts.append(timeout)
        raise URLError("still unavailable")

    ready = wait_for_http(
        url="http://service/health",
        timeout=1,
        interval=0.5,
        label="test service",
        opener=opener,
        monotonic=iter((0.0, 0.75, 1.0)).__next__,
        sleep=lambda seconds: None,
    )

    assert ready is False
    assert request_timeouts == [pytest.approx(0.25)]
