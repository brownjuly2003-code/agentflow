"""Retention and redaction policy for stored query analytics (audit F-18).

`/v1/query` takes a free-text question, and the analytics middleware used to
persist the first 1000 characters of it verbatim, with no expiry and no
redaction. Truncation bounds the *size* of what is kept; it says nothing about
the sensitivity or the lifetime. Users type PII, commercial figures and, now and
then, a credential they pasted from somewhere else -- and the admin top-queries
surface reads it all straight back out.

The policy here is deliberately conservative:

* **Nothing is stored by default.** The default record carries a
  fingerprint -- a peppered HMAC of the normalised question -- which answers
  the question analytics is actually for ("which questions repeat, and how
  often") without keeping the question.
* **Opting in stores a redacted question, never a raw one.** An operator who
  needs the text sets ``AGENTFLOW_QUERY_ANALYTICS_STORE_TEXT=true`` and gets
  emails, credential-shaped tokens, JWTs and long digit runs replaced by
  placeholders. There is no third level that stores the raw prompt: the
  operator's intent to read questions is not the user's consent to have a
  pasted secret retained.
* **Retention is finite and stated.** ``retention_days`` (default 30) is the
  contract `scripts/prune_query_analytics.py` enforces against both stores.

The fingerprint is peppered so a leaked analytics table cannot be joined
against fingerprints of the same questions computed elsewhere -- the same
reasoning as the key-lookup pepper in `security.py`. Changing the pepper
re-partitions historical fingerprints: old rows stop grouping with new ones.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

STORE_TEXT_ENV = "AGENTFLOW_QUERY_ANALYTICS_STORE_TEXT"
RETENTION_DAYS_ENV = "AGENTFLOW_QUERY_ANALYTICS_RETENTION_DAYS"
FINGERPRINT_PEPPER_ENV = "AGENTFLOW_QUERY_FINGERPRINT_PEPPER"

DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_QUERY_TEXT_CHARS = 1000
DEFAULT_FINGERPRINT_PEPPER = "agentflow-query-fingerprint-v1"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})

# Ordered: the token pattern must run before the digit-run one so that an
# api_key=1234567890123 is reported as a token rather than a number.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"), "[jwt]"),
    (
        re.compile(
            r"\b(?:sk|pk|api[-_]?key|apikey|token|bearer|secret|password|passwd|pwd)"
            r"[-_ ]*[:=]?[-_ ]*[A-Za-z0-9._~+/-]{8,}",
            re.IGNORECASE,
        ),
        "[secret]",
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b\d(?:[\d ._-]{10,26})\d\b"), "[number]"),
)

_WHITESPACE = re.compile(r"\s+")


class QueryAnalyticsPolicyError(ValueError):
    """The configured query-analytics policy is not usable."""


def _resolve_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise QueryAnalyticsPolicyError(
        f"{name}={raw!r} is not a boolean; use one of 1/true/yes/on or 0/false/no/off."
    )


@dataclass(frozen=True)
class QueryAnalyticsPolicy:
    """What may be kept from a `/v1/query` question, and for how long."""

    store_query_text: bool = False
    retention_days: int = DEFAULT_RETENTION_DAYS
    max_query_text_chars: int = DEFAULT_MAX_QUERY_TEXT_CHARS
    fingerprint_pepper: str = DEFAULT_FINGERPRINT_PEPPER

    def __post_init__(self) -> None:
        if self.retention_days < 1:
            raise QueryAnalyticsPolicyError(
                f"retention_days must be at least 1 day, got {self.retention_days}. "
                "Analytics with no expiry is what this policy exists to prevent."
            )
        if self.max_query_text_chars < 1:
            raise QueryAnalyticsPolicyError(
                f"max_query_text_chars must be positive, got {self.max_query_text_chars}"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> QueryAnalyticsPolicy:
        """Resolve the policy at boot, refusing an unusable configuration.

        Raising here rather than falling back keeps a typo in a retention
        window from silently meaning "keep questions forever".
        """
        env = os.environ if env is None else env
        raw_days = env.get(RETENTION_DAYS_ENV)
        if raw_days is None or not raw_days.strip():
            retention_days = DEFAULT_RETENTION_DAYS
        else:
            try:
                retention_days = int(raw_days.strip())
            except ValueError as exc:
                raise QueryAnalyticsPolicyError(
                    f"{RETENTION_DAYS_ENV}={raw_days!r} is not a whole number of days."
                ) from exc
        return cls(
            store_query_text=_resolve_bool(env, STORE_TEXT_ENV, default=False),
            retention_days=retention_days,
            fingerprint_pepper=env.get(FINGERPRINT_PEPPER_ENV) or DEFAULT_FINGERPRINT_PEPPER,
        )

    def fingerprint(self, question: str) -> str:
        """Stable, peppered digest of the normalised question.

        Normalisation is case-folding plus whitespace collapse, so the same
        question typed with different spacing groups together -- which is what
        makes the fingerprint a usable replacement for the text in
        top-queries.
        """
        normalised = _WHITESPACE.sub(" ", question).strip().casefold()
        return hmac.new(
            self.fingerprint_pepper.encode("utf-8"),
            normalised.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def redact(self, question: str) -> str:
        """Replace credential- and identity-shaped spans with placeholders."""
        redacted = question
        for pattern, placeholder in _REDACTIONS:
            redacted = pattern.sub(placeholder, redacted)
        return redacted

    def capture(self, question: str) -> tuple[str | None, str]:
        """Return `(query_text, query_fingerprint)` for a question.

        `query_text` is `None` unless the operator opted in, and redacted and
        truncated when they did. The fingerprint is always computed, from the
        original question: fingerprinting the redacted form would merge every
        question that differs only inside a redacted span.
        """
        digest = self.fingerprint(question)
        if not self.store_query_text:
            return None, digest
        return self.redact(question)[: self.max_query_text_chars], digest
