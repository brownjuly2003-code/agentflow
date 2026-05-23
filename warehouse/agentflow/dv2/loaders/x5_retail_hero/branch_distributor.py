from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


BRANCH_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("msk", 40),
    ("spb", 25),
    ("ekb", 15),
    ("dxb", 10),
    ("ala", 10),
)


def normalize_store_id(store_id: Any) -> str:
    if store_id is None:
        return ""

    try:
        if store_id != store_id:
            return ""
    except TypeError:
        pass

    if isinstance(store_id, float) and store_id.is_integer():
        return str(int(store_id))

    return str(store_id).strip()


def _sort_key(store_id: Any) -> tuple[int, Decimal | str]:
    normalized = normalize_store_id(store_id)
    try:
        return (0, Decimal(normalized))
    except (InvalidOperation, ValueError):
        return (1, normalized)


def distribute_stores_to_branches(store_ids: Iterable[Any]) -> dict[Any, str]:
    unique_store_ids = sorted(
        {store_id for store_id in store_ids if normalize_store_id(store_id)},
        key=_sort_key,
    )
    totals = {branch_code: 0 for branch_code, _ in BRANCH_WEIGHTS}
    total_weight = sum(weight for _, weight in BRANCH_WEIGHTS)
    branch_order = {branch_code: index for index, (branch_code, _) in enumerate(BRANCH_WEIGHTS)}

    assignments: dict[Any, str] = {}
    for store_id in unique_store_ids:
        for branch_code, weight in BRANCH_WEIGHTS:
            totals[branch_code] += weight

        branch_code = max(
            totals,
            key=lambda code: (totals[code], -branch_order[code]),
        )
        assignments[store_id] = branch_code
        totals[branch_code] -= total_weight

    return assignments
