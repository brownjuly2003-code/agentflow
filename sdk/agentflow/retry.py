import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_INITIAL_DELAY_S = 0.25
DEFAULT_MAX_DELAY_S = 30.0
DEFAULT_JITTER_FACTOR = 0.3


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    initial_delay_s: float = DEFAULT_INITIAL_DELAY_S
    max_delay_s: float = DEFAULT_MAX_DELAY_S
    jitter_factor: float = DEFAULT_JITTER_FACTOR

    def compute_delay(self, attempt: int, retry_after_s: float | None = None) -> float:
        if retry_after_s is not None:
            return min(max(retry_after_s, 0.0), self.max_delay_s)
        base = min(self.initial_delay_s * (2**attempt), self.max_delay_s)
        if self.jitter_factor == 0:
            return base
        jitter_range = base * self.jitter_factor
        jitter = random.uniform(-jitter_range, jitter_range)
        return max(0.0, min(base + jitter, self.max_delay_s))


def is_retryable_method(
    method: str,
    headers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> bool:
    normalized_method = method.upper()
    if normalized_method in {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}:
        return True
    if normalized_method != "POST" or headers is None:
        return False
    if isinstance(headers, Mapping):
        return any(key.lower() == "idempotency-key" for key in headers)
    return any(key.lower() == "idempotency-key" for key, _ in headers)
