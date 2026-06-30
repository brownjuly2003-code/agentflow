"""Bounded PII access policy.

Replaces the deleted ``masking.py`` (an unbounded SQL-lineage masker that was
bypassed three times running). The contract here is *deny*, not *mask*, and it is
bounded because the PII surface is a finite, declared set — there is no per-query
string analysis to outwit:

* **Query path** — the NL-SQL guard (:func:`serving.semantic_layer.sql_guard.
  assert_no_pii_access`) rejects any non-exempt query that can read a PII column,
  so PII is never read out of the warehouse.
* **Entity path** — a direct ``/entity/{type}/{id}`` lookup runs no SQL, so its
  payload is redacted here: every declared PII field is replaced with the constant
  :data:`REDACTED` sentinel, so PII is never returned.

The PII column set per entity and the exempt-tenant list come from
``config/pii_fields.yaml`` (unchanged schema). Exempt tenants (e.g. an internal
analytics or compliance reader) bypass both paths.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

#: Constant placeholder written over a redacted entity field. A fixed sentinel
#: (not a partial mask) keeps redaction bounded and trivially verifiable — a
#: test asserts equality, not a fuzzy pattern.
REDACTED = "[REDACTED]"


class PiiPolicy:
    """PII deny/redact policy loaded from ``config/pii_fields.yaml``."""

    def __init__(self, config_path: str | Path = "config/pii_fields.yaml"):
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML is required for the PII policy.")
        self.config_path = Path(config_path)
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        masking = config.get("masking", {}) or {}
        entity_fields = masking.get("entity_fields", {}) or {}
        # entity_type -> frozenset of declared PII field names. The yaml lists a
        # strategy per field; the deny-gate ignores it (every PII field is denied
        # the same way), so only the field name is kept.
        self.pii_fields_by_entity: dict[str, frozenset[str]] = {
            entity_type: frozenset(
                rule["field"]
                for rule in (rules or [])
                if isinstance(rule, dict) and rule.get("field")
            )
            for entity_type, rules in entity_fields.items()
        }
        self._exempt_tenants: frozenset[str] = frozenset(
            masking.get("pii_exempt_tenants", []) or []
        )

    def is_exempt(self, tenant: str | None) -> bool:
        """Whether ``tenant`` may read PII unredacted (e.g. internal analytics)."""
        return tenant in self._exempt_tenants

    def pii_fields_for_entity(self, entity_type: str) -> frozenset[str]:
        """Declared PII field names for ``entity_type`` (empty if none/unknown)."""
        return self.pii_fields_by_entity.get(entity_type, frozenset())

    def redact_entity(self, entity_type: str, data: dict, tenant: str | None) -> dict:
        """Return a copy of ``data`` with the entity's PII fields redacted.

        Each present, non-``None`` PII field is overwritten with :data:`REDACTED`.
        ``None`` values are left untouched (there is nothing to leak, and replacing
        them would falsely signal that data existed). Exempt tenants get an
        unmodified copy.
        """
        if self.is_exempt(tenant):
            return dict(data)
        redacted = dict(data)
        for field in self.pii_fields_by_entity.get(entity_type, frozenset()):
            if redacted.get(field) is not None:
                redacted[field] = REDACTED
        return redacted


_POLICY: PiiPolicy | None = None


def get_pii_policy() -> PiiPolicy:
    """Process-wide :class:`PiiPolicy`, rebuilt when ``AGENTFLOW_PII_CONFIG`` moves.

    Both the query path (NL engine) and the entity path (API router) resolve the
    policy through here so they share one config and one parsed copy.
    """
    global _POLICY
    config_path = os.getenv("AGENTFLOW_PII_CONFIG", "config/pii_fields.yaml")
    if _POLICY is None or _POLICY.config_path != Path(config_path):
        _POLICY = PiiPolicy(config_path)
    return _POLICY
