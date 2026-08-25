"""Branch attribution stamp for federated events (ADR 0012 N4).

Both node roles stamp ``source_metadata.branch`` before applying an event —
the edge on its own local apply (``emitter.py``) and the center on ingest
(``ingest.py``) — so the ``pipeline_events`` journal, Order 360 and the
cross-branch view can say which branch an event came from. One rule, one
place, so the two cannot drift.
"""

from __future__ import annotations

from agentflow_runtime.quality.validators.schema_validator import _is_cdc_event


def stamp_origin_branch(event: dict, branch: str) -> None:
    """Set ``event["source_metadata"]["branch"] = branch`` in place.

    The stamp is the node's attribution, not the sender's claim, so it
    overwrites a ``branch`` already present. A missing ``source_metadata`` is
    created. A ``source_metadata`` that is present but not a mapping is
    *replaced* for the canonical producer events (``BaseEvent`` does not
    declare the field, so such an event still validates and applies — and
    without the stamp its journal row would carry no branch and the
    cross-branch view would never see it). The one exception is a CDC-shaped
    event: ``CdcEvent`` owns ``source_metadata`` as provenance and requires a
    non-empty mapping, so a non-mapping there is the sender's defect — it is
    left alone for the validator to dead-letter rather than healed into a
    validated row with fabricated provenance.
    """
    metadata = event.get("source_metadata")
    if isinstance(metadata, dict):
        metadata["branch"] = branch
    elif _is_cdc_event(event):
        return
    else:
        event["source_metadata"] = {"branch": branch}
