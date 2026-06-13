from __future__ import annotations

from datetime import datetime

import pandas as pd

from warehouse.agentflow.dv2.loaders.x5_retail_hero.mappers import (
    map_purchases_chunk,
    rows_to_dicts,
)


def test_purchase_mapper_emits_hub_store_business_key_column():
    mapped = map_purchases_chunk(
        pd.DataFrame(
            [
                {
                    "store_id": 1,
                    "client_id": "client-1",
                    "product_id": "sku-1",
                    "transaction_id": "tx-1",
                    "express_points_received": 0,
                    "express_points_spent": 0,
                    "purchase_sum": 10,
                    "regular_points_received": 0,
                    "regular_points_spent": 0,
                    "transaction_datetime": "2026-05-29 10:00:00",
                    "product_quantity": 1,
                    "trn_sum_from_iss": 10,
                }
            ]
        ),
        datetime(2026, 5, 29, 10, 0, 0),
        {1: "msk"},
        {},
        set(),
    )

    hub_store_rows = rows_to_dicts(mapped["hub_store"])

    assert hub_store_rows[0]["store_bk"] == "msk-1"
    assert "store_code" not in hub_store_rows[0]


def test_clickhouse_connect_passes_credentials(monkeypatch):
    from warehouse.agentflow.dv2.loaders.x5_retail_hero import loader

    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def execute(self, query: str):
            calls.append({"query": query})

    monkeypatch.setattr(loader, "Client", FakeClient)

    client = loader._connect("clickhouse.local", 9000, "default", "demo")

    assert isinstance(client, FakeClient)
    assert calls == [
        {
            "host": "clickhouse.local",
            "port": 9000,
            "user": "default",
            "password": "demo",
        },
        {"query": "SELECT 1"},
    ]


def test_parts_throttle_waits_until_merges_catch_up(monkeypatch):
    from warehouse.agentflow.dv2.loaders.x5_retail_hero.loader import PartsThrottle

    class _FakeClient:
        def __init__(self, counts):
            self.counts = list(counts)

        def execute(self, query, params):
            assert "system.parts" in query
            assert params == {"database": "rv"}
            return [(self.counts.pop(0),)]

    sleeps: list[float] = []
    monkeypatch.setattr(
        "warehouse.agentflow.dv2.loaders.x5_retail_hero.loader.time.sleep",
        sleeps.append,
    )

    # Above budget twice, then merges catch up.
    throttle = PartsThrottle(_FakeClient([900, 700, 300]), "rv", max_active_parts=400)
    throttle.wait_if_needed()
    assert len(sleeps) == 2

    # Disabled throttle (0) and dry-run (client=None) never query or sleep.
    PartsThrottle(_FakeClient([]), "rv", max_active_parts=0).wait_if_needed()
    PartsThrottle(None, "rv", max_active_parts=400).wait_if_needed()
    assert len(sleeps) == 2
