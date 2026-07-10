"""At-scale data proof on the project's own synthetic generator (S13).

Scales the kitchen-appliance importer legend (docs/domain.md,
docs/generator-spec.md) to a multi-year order history directly inside
ClickHouse — the same in-database ``numbers()`` technique as
``warehouse/agentflow/dv2/synthetic_seed.sql``, parameterized by ``--days`` —
then measures three things at volume:

1. **Load**: rows/s of in-database generation per table (INSERT ... SELECT
   FROM numbers(), chunked).
2. **Query latency**: analyst-shaped queries over the full history
   (server-side elapsed, ``--query-repeats`` runs each).
3. **Correctness**: the generator-spec §12 invariants re-checked in SQL at
   scale (channel mixes, AOV bands and bimodality, branch shares, status
   flow, full GS1 mod-10 validation of every GTIN).

The target database (default ``rv_scale``) is separate from the demo ``rv``
vault; DDL is sourced from the checked-in ``raw_vault/*.sql`` files so the
scale run measures the real schema, not a tuned copy. Everything is
deterministic given (--days, --anchor): no wall-clock randomness enters the
data itself.

Exit code: 0 when every invariant passes, 2 otherwise.

Example (stand):
    .venv/bin/python scripts/benchmark_scale_own_data.py \
        --days 1460 --report-json /tmp/scale-report.json \
        --report-md /tmp/scale-report.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_VAULT = PROJECT_ROOT / "warehouse" / "agentflow" / "dv2" / "raw_vault"

# Daily order rates by channel/branch — generator-spec.md §1 master matrix.
DAILY_MP = 1750
DAILY_SITE = 55
DAILY_B2B = {"msk": 70, "spb": 35, "ekb": 25, "dxb": 15, "ala": 15}
DAILY_ORDERS = DAILY_MP + DAILY_SITE + sum(DAILY_B2B.values())  # 1,965 (§1)
# ≈ units sold per day (mp ~1.05 lines × 1 unit, B2B ~33 units/order, §1/§2);
# drives the per-unit Chestny Znak code population like the seed's container
# sample, uniform across the 160-SKU catalog.
DAILY_UNITS = 7300
# Retail identities per 365 days: ~150k marketplace buyer ids + ~9k D2C (§7).
RETAIL_IDS_PER_YEAR = 159_000
DEALERS = {"msk": 190, "spb": 100, "ekb": 70, "dxb": 60, "ala": 80}  # §7

# Pinned 13th-digit string for the 160 synthetic GTIN stems — identical to
# warehouse/agentflow/dv2/synthetic_seed.sql and asserted against
# reference/gs1.py by tests/unit/test_generator_spec_invariants.py.
GTIN_CHECK_DIGITS = (
    "652085086309309649318741741075975985985208308632608638641971874201"
    "975295298538530937630961864104104164297597520820530830763163197454"
    "1874974298298598207537530960"
)

# DDL files defining the scale-run scope: the order axis and the marking axis.
# Customer PII / loyalty / product-catalog satellites stay demo-scale by the
# legend itself (fixed 500-dealer book, 160-SKU catalog) and are out of scope.
DDL_FILES = [
    "hubs/hub_store.sql",
    "hubs/hub_customer.sql",
    "hubs/hub_product.sql",
    "hubs/hub_order.sql",
    "hubs/hub_marking_code.sql",
    "links/lnk_order_customer.sql",
    "links/lnk_order_product.sql",
    "links/lnk_order_store.sql",
    "links/lnk_product_marking.sql",
    "satellites/sat_order_header__bitrix__msk.sql",
    "satellites/sat_order_header__bitrix__spb.sql",
    "satellites/sat_order_header__bitrix__ekb.sql",
    "satellites/sat_order_header__bitrix__dxb.sql",
    "satellites/sat_order_header__bitrix__ala.sql",
    "satellites/sat_order_pricing__1c__msk.sql",
    "satellites/sat_order_pricing__1c__spb.sql",
    "satellites/sat_order_pricing__1c__ekb.sql",
    "satellites/sat_order_pricing__1c__dxb.sql",
    "satellites/sat_order_pricing__1c__ala.sql",
    "satellites/sat_marking_code_gs1__1c__global.sql",
]


@dataclass
class Bands:
    """Contiguous order-number bands per channel/branch (seed convention)."""

    days: int
    mp: int = field(init=False)
    site: int = field(init=False)
    b2b: dict[str, int] = field(init=False)
    cuts: list[tuple[int, str, str]] = field(init=False)  # (upper, rs, channel)
    total: int = field(init=False)

    def __post_init__(self) -> None:
        self.mp = DAILY_MP * self.days
        self.site = DAILY_SITE * self.days
        self.b2b = {b: n * self.days for b, n in DAILY_B2B.items()}
        upper = self.mp
        cuts = [(upper, "mp__msk", "marketplace")]
        upper += self.site
        cuts.append((upper, "site__msk", "d2c"))
        for branch in ("msk", "spb", "ekb", "dxb", "ala"):
            upper += self.b2b[branch]
            cuts.append((upper, f"bitrix__{branch}", "b2b"))
        self.cuts = cuts
        self.total = upper

    def record_source_sql(self) -> str:
        arms = ", ".join(f"number < {u}, '{rs}'" for u, rs, _ in self.cuts[:-1])
        return f"multiIf({arms}, '{self.cuts[-1][1]}')"

    def band_of(self, n: int) -> tuple[str, str]:
        for upper, rs, channel in self.cuts:
            if n < upper:
                return rs, channel
        raise ValueError(f"order number {n} out of range {self.total}")

    def order_bk_sql(self) -> str:
        return f"concat({self.record_source_sql()}, '__', lpad(toString(number), 9, '0'))"

    def order_bk(self, n: int) -> str:
        rs, _ = self.band_of(n)
        return f"{rs}__{n:09d}"

    def range_for(self, record_sources: list[str]) -> tuple[int, int]:
        """(offset, count) of the contiguous number range covering the given
        record sources — they must be adjacent in the band order."""
        lowers, uppers = [], []
        prev_upper = 0
        for upper, rs, _ in self.cuts:
            if rs in record_sources:
                lowers.append(prev_upper)
                uppers.append(upper)
            prev_upper = upper
        if not lowers:
            raise ValueError(f"no bands match {record_sources}")
        offset = min(lowers)
        count = max(uppers) - offset
        if count != sum(u - lo for lo, u in zip(lowers, uppers, strict=True)):
            raise ValueError(f"bands {record_sources} are not contiguous")
        return offset, count


# Per-channel total_amount expressions — identical formulas to
# satellite_seed.sql / satellite_seed_all_branches.sql (§1 mean checks:
# mp ≈2,150 · d2c ≈3,300 · B2B RU ≈52k · dxb ≈90k · ala ≈45k).
AMOUNT_BY_RS = {
    "mp__msk": "toDecimal64(1500 + (number * 17) % 1301, 2)",
    "site__msk": "toDecimal64(2000 + (number * 37) % 2601, 2)",
    "bitrix__msk": "toDecimal64(30000 + (number * 329) % 44001, 2)",
    "bitrix__spb": "toDecimal64(30000 + (number * 329) % 44001, 2)",
    "bitrix__ekb": "toDecimal64(30000 + (number * 329) % 44001, 2)",
    "bitrix__dxb": "toDecimal64(60000 + (number * 355) % 60001, 2)",
    "bitrix__ala": "toDecimal64(25000 + (number * 263) % 40001, 2)",
}

STATUS_SQL = (
    "multiIf(number % 100 < 8, 'pending', number % 100 < 18, 'confirmed', "
    "number % 100 < 30, 'shipped', number % 100 < 92, 'delivered', 'cancelled')"
)


class ClickHouseHTTP:
    """Minimal ClickHouse HTTP client (stdlib only, same transport as
    src/serving/backends/clickhouse_backend.py)."""

    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.base = f"http://{host}:{port}/"
        self.user = user
        self.password = password

    def _request(self, sql: str, timeout: float) -> tuple[bytes, dict[str, str]]:
        params = {
            "user": self.user,
            "password": self.password,
            # Chunked INSERT ... SELECT statements can be long-running; keep
            # the HTTP session honest about it.
            "max_execution_time": "0",
        }
        url = self.base + "?" + urllib.parse.urlencode(params)
        request = _build_request(url, sql.encode("utf-8"))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:  # surface CH's error text
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail[:2000]}") from exc

    def command(self, sql: str, timeout: float = 600.0) -> dict[str, object]:
        """DDL / INSERT. Returns wall seconds + X-ClickHouse-Summary counters."""
        started = time.perf_counter()
        _, headers = self._request(sql, timeout)
        wall = time.perf_counter() - started
        summary: dict[str, object] = {}
        raw = headers.get("X-Clickhouse-Summary") or headers.get("X-ClickHouse-Summary")
        if raw:
            try:
                summary = json.loads(raw)
            except json.JSONDecodeError:
                summary = {}
        return {"wall_s": wall, "written_rows": int(summary.get("written_rows", 0) or 0)}

    def query(self, sql: str, timeout: float = 600.0) -> dict[str, object]:
        """SELECT with FORMAT JSON: rows + server-side statistics."""
        body, _ = self._request(sql.rstrip().rstrip(";") + " FORMAT JSON", timeout)
        payload = json.loads(body)
        return {
            "rows": payload.get("data", []),
            "elapsed_s": float(payload.get("statistics", {}).get("elapsed", 0.0)),
            "rows_read": int(payload.get("statistics", {}).get("rows_read", 0)),
            "bytes_read": int(payload.get("statistics", {}).get("bytes_read", 0)),
        }

    def scalar(self, sql: str, timeout: float = 600.0) -> object:
        rows = self.query(sql, timeout)["rows"]
        if not rows:
            raise RuntimeError(f"query returned no rows: {sql[:200]}")
        return next(iter(rows[0].values()))


def _build_request(url: str, data: bytes) -> urllib.request.Request:
    return urllib.request.Request(
        url, data=data, headers={"Content-Type": "text/plain; charset=utf-8"}, method="POST"
    )


def load_ddl(database: str) -> list[str]:
    statements = []
    for rel in DDL_FILES:
        sql = (RAW_VAULT / rel).read_text(encoding="utf-8")
        statements.append(sql.replace("rv.", f"{database}."))
    return statements


def chunk_ranges(offset: int, count: int, chunk: int) -> list[tuple[int, int]]:
    ranges = []
    position = offset
    end = offset + count
    while position < end:
        step = min(chunk, end - position)
        ranges.append((position, step))
        position += step
    return ranges


@dataclass
class LoadStats:
    table: str
    rows: int = 0
    seconds: float = 0.0

    @property
    def rows_per_s(self) -> float:
        return self.rows / self.seconds if self.seconds else 0.0


def run_insert(
    ch: ClickHouseHTTP,
    stats: dict[str, LoadStats],
    table: str,
    insert_sql_for_range: object,
    offset: int,
    count: int,
    chunk: int,
) -> None:
    entry = stats.setdefault(table, LoadStats(table))
    for chunk_offset, chunk_count in chunk_ranges(offset, count, chunk):
        result = ch.command(insert_sql_for_range(chunk_offset, chunk_count))
        entry.rows += int(result["written_rows"])
        entry.seconds += float(result["wall_s"])


def generate(
    ch: ClickHouseHTTP,
    db: str,
    bands: Bands,
    anchor: str,
    retail_n: int,
    units: int,
    chunk: int,
) -> dict[str, LoadStats]:
    stats: dict[str, LoadStats] = {}
    rs_sql = bands.record_source_sql()
    order_bk = bands.order_bk_sql()
    window_s = bands.days * 86400
    order_date = (
        f"parseDateTime64BestEffort('{anchor}', 3) "
        f"- toIntervalSecond(cityHash64(number + 424243) % {window_s})"
    )

    # --- hub_store: 6 fixed store codes (footprint, domain.md §1) ---
    ch.command(
        f"INSERT INTO {db}.hub_store (store_hk, store_bk, load_ts, record_source) "
        "SELECT MD5(store_code), store_code, now64(), '1c__global' FROM "
        "(SELECT arrayJoin(['msk-01','msk-02','spb-01','ekb-01','dxb-01','ala-01']) AS store_code)"
    )

    # --- hub_customer: retail pool scaled by history + fixed dealer book ---
    dealer_arms, lower = [], retail_n
    for branch, n in DEALERS.items():
        upper = lower + n
        dealer_arms.append((upper, f"1c__{branch}"))
        lower = upper
    total_customers = lower
    arms = f"number < {retail_n}, '1c__msk', " + ", ".join(
        f"number < {u}, '{rs}'" for u, rs in dealer_arms[:-1]
    )
    customer_rs = f"multiIf({arms}, '{dealer_arms[-1][1]}')"
    run_insert(
        ch,
        stats,
        "hub_customer",
        lambda o, c: (
            f"INSERT INTO {db}.hub_customer (customer_hk, customer_bk, load_ts, record_source) "
            f"SELECT MD5(toString(number)), concat('CUST-', lpad(toString(number), 9, '0')), "
            f"now64(), {customer_rs} FROM numbers({o}, {c})"
        ),
        0,
        total_customers,
        chunk,
    )

    # --- hub_product: the 160-SKU catalog (fixed by the legend, §3) ---
    ch.command(
        f"INSERT INTO {db}.hub_product (product_hk, product_bk, load_ts, record_source) "
        "SELECT MD5(sku), sku, now64(), '1c__msk' FROM "
        "(SELECT concat('SKU-', lpad(toString(number), 5, '0')) AS sku FROM numbers(160))"
    )

    # --- hub_order ---
    run_insert(
        ch,
        stats,
        "hub_order",
        lambda o, c: (
            f"INSERT INTO {db}.hub_order (order_hk, order_bk, load_ts, record_source) "
            f"SELECT MD5(order_bk), order_bk, now64(), record_source FROM "
            f"(SELECT number, {rs_sql} AS record_source, {order_bk} AS order_bk "
            f"FROM numbers({o}, {c}))"
        ),
        0,
        bands.total,
        chunk,
    )

    # --- lnk_order_customer: retail draw for mp/site, branch dealer bands for B2B ---
    dealer_pick_arms = []
    lower = retail_n
    for branch, n in DEALERS.items():
        upper = lower + n
        dealer_pick_arms.append((f"bitrix__{branch}", f"{lower} + (cityHash64(number) % {n})"))
        lower = upper
    cust_arms = f"number < {bands.cuts[1][0]}, cityHash64(number) % {retail_n}, " + ", ".join(
        f"record_source = '{rs}', {expr}" for rs, expr in dealer_pick_arms[:-1]
    )
    customer_pick = f"multiIf({cust_arms}, {dealer_pick_arms[-1][1]})"
    run_insert(
        ch,
        stats,
        "lnk_order_customer",
        lambda o, c: (
            f"INSERT INTO {db}.lnk_order_customer "
            f"(link_hk, order_hk, customer_hk, load_ts, record_source) "
            f"SELECT MD5(concat(order_bk, '|', toString(customer_number))), MD5(order_bk), "
            f"MD5(toString(customer_number)), now64(), record_source FROM "
            f"(SELECT number, {rs_sql} AS record_source, {order_bk} AS order_bk, "
            f"{customer_pick} AS customer_number FROM numbers({o}, {c}))"
        ),
        0,
        bands.total,
        chunk,
    )

    # --- lnk_order_store: msk fulfils mp+site+its B2B; regions their own B2B ---
    store_pick = (
        f"multiIf(number < {bands.cuts[2][0]}, if(number % 2 = 0, 'msk-01', 'msk-02'), "
        f"number < {bands.cuts[3][0]}, 'spb-01', number < {bands.cuts[4][0]}, 'ekb-01', "
        f"number < {bands.cuts[5][0]}, 'dxb-01', 'ala-01')"
    )
    run_insert(
        ch,
        stats,
        "lnk_order_store",
        lambda o, c: (
            f"INSERT INTO {db}.lnk_order_store "
            f"(link_hk, order_hk, store_hk, load_ts, record_source) "
            f"SELECT MD5(concat(order_bk, '|', store_code)), MD5(order_bk), MD5(store_code), "
            f"now64(), '1c__global' FROM "
            f"(SELECT number, {order_bk} AS order_bk, {store_pick} AS store_code "
            f"FROM numbers({o}, {c}))"
        ),
        0,
        bands.total,
        chunk,
    )

    # --- lnk_order_product: line counts per §2, ABC skew for retail (§3) ---
    line_count = (
        f"multiIf(number < {bands.cuts[0][0]}, if(number % 20 = 0, 2, 1), "
        f"number < {bands.cuts[1][0]}, multiIf(number % 100 < 75, 1, number % 100 < 95, 2, 3), "
        f"number < {bands.cuts[4][0]}, 3 + (cityHash64(number) % 8), "
        f"number < {bands.cuts[5][0]}, 4 + (cityHash64(number) % 9), "
        f"3 + (cityHash64(number) % 6))"
    )
    retail_upper = bands.cuts[1][0]
    sku_pick = (
        f"if(number < {retail_upper}, "
        "multiIf(cityHash64(number * 31 + i) % 100 < 55, cityHash64(number * 37 + i) % 24, "
        "cityHash64(number * 31 + i) % 100 < 90, 24 + (cityHash64(number * 37 + i) % 56), "
        "80 + (cityHash64(number * 37 + i) % 80)), "
        "cityHash64(number * 31 + i) % 160)"
    )
    run_insert(
        ch,
        stats,
        "lnk_order_product",
        lambda o, c: (
            f"INSERT INTO {db}.lnk_order_product "
            f"(link_hk, order_hk, product_hk, load_ts, record_source) "
            f"SELECT MD5(concat(order_bk, '|', toString(p))), MD5(order_bk), "
            f"MD5(concat('SKU-', lpad(toString(p), 5, '0'))), now64(), '1c__msk' FROM "
            f"(SELECT number, {order_bk} AS order_bk, {line_count} AS line_count "
            f"FROM numbers({o}, {c})) "
            f"ARRAY JOIN arrayMap(i -> {sku_pick}, range(line_count)) AS p"
        ),
        0,
        bands.total,
        chunk,
    )

    # --- order header satellites: msk covers mp+site+B2B msk; regions their own ---
    sat_scopes = {
        "msk": ["mp__msk", "site__msk", "bitrix__msk"],
        "spb": ["bitrix__spb"],
        "ekb": ["bitrix__ekb"],
        "dxb": ["bitrix__dxb"],
        "ala": ["bitrix__ala"],
    }
    channel_arms = ", ".join(f"number < {u}, '{ch_}'" for u, _, ch_ in bands.cuts[:-1])
    channel_sql = f"multiIf({channel_arms}, '{bands.cuts[-1][2]}')"
    amount_arms = ", ".join(f"number < {u}, {AMOUNT_BY_RS[rs]}" for u, rs, _ in bands.cuts[:-1])
    amount_sql = f"multiIf({amount_arms}, {AMOUNT_BY_RS[bands.cuts[-1][1]]})"
    for branch, scope in sat_scopes.items():
        offset, count = bands.range_for(scope)
        header = f"sat_order_header__bitrix__{branch}"
        run_insert(
            ch,
            stats,
            header,
            lambda o, c, header=header, branch=branch: (
                f"INSERT INTO {db}.{header} "
                f"(order_hk, load_ts, hash_diff, record_source, order_date, channel, "
                f"order_status, total_amount, is_deleted) "
                f"SELECT MD5(order_bk), now64(3), MD5(concat(order_bk, '|hdr|v1')), "
                f"'bitrix__{branch}', {order_date}, {channel_sql}, {STATUS_SQL}, "
                f"{amount_sql}, 0 FROM "
                f"(SELECT number, {order_bk} AS order_bk FROM numbers({o}, {c}))"
            ),
            offset,
            count,
            chunk,
        )
        pricing = f"sat_order_pricing__1c__{branch}"
        run_insert(
            ch,
            stats,
            pricing,
            lambda o, c, pricing=pricing, branch=branch: (
                f"INSERT INTO {db}.{pricing} "
                f"(order_hk, load_ts, hash_diff, record_source, subtotal_amount, "
                f"discount_amount, tax_amount, shipping_cost, is_deleted) "
                f"SELECT MD5(order_bk), now64(3), MD5(concat(order_bk, '|prc|v1')), "
                f"'1c__{branch}', subtotal_amount, "
                f"toDecimal64(subtotal_amount * 0.02 * (number % 4), 2), "
                f"toDecimal64(subtotal_amount * 0.20, 2), "
                f"toDecimal64(if(number < {retail_upper}, 199 + (number % 5) * 100, "
                f"500 + (number % 3) * 300), 2), 0 FROM "
                f"(SELECT number, {order_bk} AS order_bk, {amount_sql} AS subtotal_amount "
                f"FROM numbers({o}, {c}))"
            ),
            offset,
            count,
            chunk,
        )

    # --- marking axis: 160 SKU templates + per-unit codes (units ≈ 7,300/day) ---
    gtin_stem = (
        "concat(toString(460 + (sku_slot % 10)), "
        "lpad(toString(200000 + sku_slot * 617), 9, '0'), "
        f"substring('{GTIN_CHECK_DIGITS}', sku_slot + 1, 1))"
    )
    ch.command(
        f"INSERT INTO {db}.hub_marking_code "
        f"(marking_code_hk, marking_code_bk, load_ts, record_source) "
        f"SELECT MD5(bk), bk, now64(), '1c__global' FROM "
        f"(SELECT concat('CZ-SKU-', lpad(toString(number), 5, '0')) AS bk FROM numbers(160))"
    )
    ch.command(
        f"INSERT INTO {db}.sat_marking_code_gs1__1c__global "
        f"(marking_code_hk, load_ts, hash_diff, record_source, gs1_gtin, serial_number, "
        f"marking_status, is_deleted) "
        f"SELECT MD5(bk), now64(3), MD5(concat(bk, '|gs1|v1')), '1c__global', {gtin_stem}, "
        f"CAST(NULL, 'Nullable(String)'), 'issued', 0 FROM "
        f"(SELECT number AS sku_slot, concat('CZ-SKU-', lpad(toString(number), 5, '0')) AS bk "
        f"FROM numbers(160))"
    )
    ch.command(
        f"INSERT INTO {db}.lnk_product_marking "
        f"(link_hk, product_hk, marking_code_hk, load_ts, record_source) "
        f"SELECT MD5(concat(product_bk, '|', bk)), MD5(product_bk), MD5(bk), now64(), "
        f"'1c__global' FROM "
        f"(SELECT concat('SKU-', lpad(toString(number), 5, '0')) AS product_bk, "
        f"concat('CZ-SKU-', lpad(toString(number), 5, '0')) AS bk FROM numbers(160))"
    )
    unit_bk = (
        "concat('CZU-', lpad(toString(number % 160), 5, '0'), '-', "
        "lpad(toString(intDiv(number, 160)), 9, '0'))"
    )
    run_insert(
        ch,
        stats,
        "hub_marking_code",
        lambda o, c: (
            f"INSERT INTO {db}.hub_marking_code "
            f"(marking_code_hk, marking_code_bk, load_ts, record_source) "
            f"SELECT MD5({unit_bk}), {unit_bk}, now64(), '1c__global' FROM numbers({o}, {c})"
        ),
        0,
        units,
        chunk,
    )
    run_insert(
        ch,
        stats,
        "sat_marking_code_gs1__1c__global",
        lambda o, c: (
            f"INSERT INTO {db}.sat_marking_code_gs1__1c__global "
            f"(marking_code_hk, load_ts, hash_diff, record_source, gs1_gtin, serial_number, "
            f"marking_status, is_deleted) "
            f"SELECT MD5(bk), now64(3), MD5(concat(bk, '|gs1|v1')), '1c__global', {gtin_stem}, "
            f"lpad(toString(intDiv(number, 160)), 9, '0'), "
            f"multiIf(number % 100 < 25, 'issued', number % 100 < 85, 'in_circulation', "
            f"'withdrawn'), 0 FROM "
            f"(SELECT number, number % 160 AS sku_slot, {unit_bk} AS bk FROM numbers({o}, {c}))"
        ),
        0,
        units,
        chunk,
    )
    run_insert(
        ch,
        stats,
        "lnk_product_marking",
        lambda o, c: (
            f"INSERT INTO {db}.lnk_product_marking "
            f"(link_hk, product_hk, marking_code_hk, load_ts, record_source) "
            f"SELECT MD5(concat(product_bk, '|', bk)), MD5(product_bk), MD5(bk), now64(), "
            f"'1c__global' FROM "
            f"(SELECT concat('SKU-', lpad(toString(number % 160), 5, '0')) AS product_bk, "
            f"{unit_bk} AS bk FROM numbers({o}, {c}))"
        ),
        0,
        units,
        chunk,
    )
    return stats


def analyst_queries(db: str, bands: Bands) -> dict[str, str]:
    probe_bk = bands.order_bk(bands.total // 2)
    return {
        "monthly_revenue_by_channel": (
            f"SELECT toStartOfMonth(order_date) AS month, channel, "
            f"sum(total_amount) AS revenue, count() AS orders "
            f"FROM {db}.v_order_header_all WHERE order_status != 'cancelled' "
            f"GROUP BY month, channel ORDER BY month, channel"
        ),
        "aov_by_channel": (
            f"SELECT channel, avg(total_amount) AS aov, "
            f"quantile(0.5)(total_amount) AS median_check, count() AS orders "
            f"FROM {db}.v_order_header_all GROUP BY channel ORDER BY channel"
        ),
        "sku_volume_ranking_marketplace": (
            f"SELECT product_hk, count() AS lines FROM {db}.lnk_order_product "
            f"WHERE order_hk IN (SELECT order_hk FROM {db}.hub_order "
            f"WHERE record_source = 'mp__msk') "
            f"GROUP BY product_hk ORDER BY lines DESC"
        ),
        "branch_revenue_shares": (
            f"SELECT record_source, sum(total_amount) AS revenue, count() AS orders "
            f"FROM {db}.v_order_header_all GROUP BY record_source ORDER BY revenue DESC"
        ),
        # IN-subquery shape, not JOIN: a point lookup must resolve through the
        # sats' (order_hk, …) primary index instead of hashing a multi-million
        # row right side — the same access pattern the serving layer uses.
        "order_360_point_lookup": (
            f"SELECT order_date, order_status, total_amount, "
            f"(SELECT count() FROM {db}.lnk_order_product WHERE order_hk IN "
            f"(SELECT order_hk FROM {db}.hub_order WHERE order_bk = '{probe_bk}')) AS line_count "
            f"FROM {db}.v_order_header_all "
            f"WHERE order_hk IN "
            f"(SELECT order_hk FROM {db}.hub_order WHERE order_bk = '{probe_bk}')"
        ),
        "marking_status_distribution": (
            f"SELECT marking_status, count() AS codes "
            f"FROM {db}.sat_marking_code_gs1__1c__global GROUP BY marking_status"
        ),
    }


def run_queries(
    ch: ClickHouseHTTP, queries: dict[str, str], repeats: int
) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for name, sql in queries.items():
        elapsed: list[float] = []
        rows_read = bytes_read = result_rows = 0
        for _ in range(repeats):
            outcome = ch.query(sql)
            elapsed.append(float(outcome["elapsed_s"]))
            rows_read = int(outcome["rows_read"])
            bytes_read = int(outcome["bytes_read"])
            result_rows = len(list(outcome["rows"]))
        results[name] = {
            "elapsed_s_min": min(elapsed),
            "elapsed_s_median": statistics.median(elapsed),
            "elapsed_s_max": max(elapsed),
            "rows_read": rows_read,
            "bytes_read": bytes_read,
            "result_rows": result_rows,
        }
    return results


def within(value: float, low: float, high: float) -> bool:
    return low <= value <= high


def correctness_checks(
    ch: ClickHouseHTTP, db: str, bands: Bands, retail_n: int, units: int
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # 1. Row reconciliation — generation integrity, not statistics.
    expected = {
        "hub_order": bands.total,
        "lnk_order_customer": bands.total,
        "lnk_order_store": bands.total,
        "hub_customer": retail_n + sum(DEALERS.values()),
        "hub_product": 160,
        "hub_store": 6,
        "hub_marking_code": 160 + units,
        "lnk_product_marking": 160 + units,
        "sat_marking_code_gs1__1c__global": 160 + units,
    }
    for table, want in expected.items():
        got = int(ch.scalar(f"SELECT count() FROM {db}.{table}"))  # type: ignore[arg-type]
        add(f"rowcount:{table}", got == want, f"expected {want:,}, got {got:,}")
    header_total = int(
        ch.scalar(f"SELECT count() FROM {db}.v_order_header_all")  # type: ignore[arg-type]
    )
    add(
        "rowcount:order_header_sats",
        header_total == bands.total,
        f"expected {bands.total:,}, got {header_total:,}",
    )

    # 2. §12.2 order-count mix.
    mix = {
        str(row["channel"]): int(row["orders"])
        for row in ch.query(
            f"SELECT channel, count() AS orders FROM {db}.v_order_header_all GROUP BY channel"
        )["rows"]
    }
    total = sum(mix.values())
    mp_share = mix.get("marketplace", 0) / total
    b2b_share = mix.get("b2b", 0) / total
    d2c_share = mix.get("d2c", 0) / total
    mix_ok = (
        within(mp_share, 0.88, 0.90)
        and within(b2b_share, 0.07, 0.09)
        and within(d2c_share, 0.02, 0.04)
    )
    add(
        "§12.2 order-count mix",
        mix_ok,
        f"mp {mp_share:.1%} · b2b {b2b_share:.1%} · d2c {d2c_share:.1%}",
    )

    # 3. §12.3 revenue mix.
    revenue = {
        str(row["channel"]): float(row["revenue"])
        for row in ch.query(
            f"SELECT channel, sum(total_amount) AS revenue FROM {db}.v_order_header_all "
            f"GROUP BY channel"
        )["rows"]
    }
    revenue_total = sum(revenue.values())
    b2b_rev = revenue.get("b2b", 0.0) / revenue_total
    mp_rev = revenue.get("marketplace", 0.0) / revenue_total
    add(
        "§12.3 revenue mix",
        within(b2b_rev, 0.65, 0.72) and within(mp_rev, 0.27, 0.33),
        f"b2b {b2b_rev:.1%} · mp {mp_rev:.1%}",
    )

    # 4. §12.4 AOV bands + bimodality (no channel average between 10k and 25k).
    aov = {
        str(row["channel"]): float(row["aov"])
        for row in ch.query(
            f"SELECT channel, avg(total_amount) AS aov FROM {db}.v_order_header_all "
            f"GROUP BY channel"
        )["rows"]
    }
    bimodal = all(not (10_000 < value < 25_000) for value in aov.values())
    add(
        "§12.4 AOV bands + bimodality",
        within(aov.get("marketplace", 0.0), 1_500, 3_000)
        and within(aov.get("b2b", 0.0), 30_000, 80_000)
        and bimodal,
        " · ".join(f"{k} {v:,.0f} ₽" for k, v in sorted(aov.items())),
    )

    # 5. §12.10 branch revenue shares (msk = mp + site + its own B2B).
    by_rs = {
        str(row["record_source"]): float(row["revenue"])
        for row in ch.query(
            f"SELECT record_source, sum(total_amount) AS revenue "
            f"FROM {db}.v_order_header_all GROUP BY record_source"
        )["rows"]
    }
    msk_share = sum(v for k, v in by_rs.items() if k.endswith("__msk")) / revenue_total
    add("§12.10 msk revenue share", within(msk_share, 0.55, 0.65), f"msk {msk_share:.1%}")

    # 6. Status flow steady state 8/10/12/62/8 (±0.5 pp).
    status = {
        str(row["order_status"]): int(row["orders"]) / total
        for row in ch.query(
            f"SELECT order_status, count() AS orders FROM {db}.v_order_header_all "
            f"GROUP BY order_status"
        )["rows"]
    }
    status_expected = {
        "pending": 0.08,
        "confirmed": 0.10,
        "shipped": 0.12,
        "delivered": 0.62,
        "cancelled": 0.08,
    }
    status_ok = all(
        abs(status.get(name, 0.0) - share) <= 0.005 for name, share in status_expected.items()
    )
    add(
        "status flow 8/10/12/62/8",
        status_ok,
        " · ".join(f"{k} {status.get(k, 0.0):.1%}" for k in status_expected),
    )

    # 7. §12.7 every GTIN valid: full-scan GS1 mod-10 + EAEU prefix, in SQL.
    gtin = ch.query(
        f"SELECT countIf(NOT (length(gs1_gtin) = 13 "
        f"AND toUInt16OrZero(substring(gs1_gtin, 1, 3)) BETWEEN 460 AND 469 "
        f"AND toUInt8OrZero(substring(gs1_gtin, 13, 1)) = "
        f"(10 - (arraySum(arrayMap(i -> toUInt8OrZero(substring(gs1_gtin, i, 1)) * "
        f"if(i % 2 = 1, 1, 3), range(1, 13))) % 10)) % 10)) AS invalid, "
        f"count() AS total FROM {db}.sat_marking_code_gs1__1c__global"
    )["rows"][0]
    add(
        "§12.7 GTIN validity (full scan)",
        int(gtin["invalid"]) == 0,
        f"{int(gtin['invalid'])} invalid of {int(gtin['total']):,}",
    )

    # 8. Per-unit marking status split 25/60/15 (±0.5 pp).
    marking = {
        str(row["marking_status"]): int(row["codes"])
        for row in ch.query(
            f"SELECT marking_status, count() AS codes "
            f"FROM {db}.sat_marking_code_gs1__1c__global WHERE serial_number IS NOT NULL "
            f"GROUP BY marking_status"
        )["rows"]
    }
    marking_total = sum(marking.values())
    marking_expected = {"issued": 0.25, "in_circulation": 0.60, "withdrawn": 0.15}
    marking_ok = marking_total == units and all(
        abs(marking.get(name, 0) / marking_total - share) <= 0.005
        for name, share in marking_expected.items()
    )
    add(
        "marking status 25/60/15",
        marking_ok,
        " · ".join(
            f"{k} {marking.get(k, 0) / max(marking_total, 1):.1%}" for k in marking_expected
        ),
    )
    return checks


def disk_footprint(ch: ClickHouseHTTP, db: str) -> list[dict[str, object]]:
    return list(
        ch.query(
            f"SELECT table, sum(rows) AS rows, sum(data_compressed_bytes) AS compressed, "
            f"sum(data_uncompressed_bytes) AS uncompressed FROM system.parts "
            f"WHERE database = '{db}' AND active GROUP BY table ORDER BY rows DESC"
        )["rows"]
    )


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        f"# At-scale proof on own data — {report['days']} days of legend history",
        "",
        f"> Generated {report['generated_at']} · database `{report['database']}` · "
        f"anchor `{report['anchor']}` · ClickHouse `{report['clickhouse_version']}`",
        ">",
        "> Generator: docs/generator-spec.md legend rates scaled in-database "
        "(`numbers()` INSERT-SELECT, deterministic). Host class in the companion "
        "note — do not compare across hardware.",
        "",
        "## Volume",
        "",
        f"- Orders: **{report['orders']:,}** ({report['days']} days ≈ "
        f"{report['days'] / 365:.1f} years at 1,965/day)",
        f"- Per-unit marking codes: **{report['units']:,}**",
        f"- Total rows: **{report['total_rows']:,}** · compressed on disk: "
        f"**{report['total_compressed_bytes'] / 1e9:.2f} GB** "
        f"(uncompressed {report['total_uncompressed_bytes'] / 1e9:.2f} GB)",
        "",
        "## Load (in-database generation)",
        "",
        "| Table | Rows | Seconds | Rows/s |",
        "|---|---:|---:|---:|",
    ]
    for entry in report["load"]:  # type: ignore[union-attr]
        lines.append(
            f"| {entry['table']} | {entry['rows']:,} | {entry['seconds']:.1f} | "
            f"{entry['rows_per_s']:,.0f} |"
        )
    lines += [
        f"| **total** | **{report['load_total_rows']:,}** | "
        f"**{report['load_total_seconds']:.1f}** | **{report['load_total_rows_per_s']:,.0f}** |",
        "",
        "## Analyst-query latency (server-side elapsed)",
        "",
        "| Query | Median s | Min s | Max s | Rows read | Result rows |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, entry in report["queries"].items():  # type: ignore[union-attr]
        lines.append(
            f"| {name} | {entry['elapsed_s_median']:.3f} | {entry['elapsed_s_min']:.3f} | "
            f"{entry['elapsed_s_max']:.3f} | {entry['rows_read']:,} | {entry['result_rows']:,} |"
        )
    lines += [
        "",
        "## Correctness at scale (generator-spec §12)",
        "",
        "| Check | Verdict | Detail |",
        "|---|---|---|",
    ]
    for check in report["checks"]:  # type: ignore[union-attr]
        verdict = "PASS" if check["passed"] else "**FAIL**"
        lines.append(f"| {check['name']} | {verdict} | {check['detail']} |")
    lines += [
        "",
        "## Disk footprint by table",
        "",
        "| Table | Rows | Compressed MB | Uncompressed MB |",
        "|---|---:|---:|---:|",
    ]
    for entry in report["disk"]:  # type: ignore[union-attr]
        lines.append(
            f"| {entry['table']} | {int(entry['rows']):,} | "
            f"{int(entry['compressed']) / 1e6:,.1f} | {int(entry['uncompressed']) / 1e6:,.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--user", default="default")
    parser.add_argument("--password", default="")
    parser.add_argument("--database", default="rv_scale")
    parser.add_argument("--days", type=int, default=365, help="days of history at legend rates")
    parser.add_argument(
        "--anchor",
        default=None,
        help="fixed timestamp the history window ends at (default: now, recorded in report)",
    )
    parser.add_argument("--chunk", type=int, default=1_000_000, help="numbers() rows per INSERT")
    parser.add_argument("--query-repeats", type=int, default=5)
    parser.add_argument("--skip-generate", action="store_true", help="measure an existing database")
    parser.add_argument("--drop-after", action="store_true", help="drop the database at the end")
    parser.add_argument("--report-json", default=None)
    parser.add_argument("--report-md", default=None)
    args = parser.parse_args()

    if args.days < 1:
        print("--days must be >= 1", file=sys.stderr)
        return 1

    ch = ClickHouseHTTP(args.host, args.port, args.user, args.password)
    db = args.database
    bands = Bands(args.days)
    retail_n = max(2000, round(RETAIL_IDS_PER_YEAR * args.days / 365))
    units = DAILY_UNITS * args.days
    anchor = args.anchor or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000")

    version = str(ch.scalar("SELECT version()"))
    print(f"ClickHouse {version} at {args.host}:{args.port}, database {db}")
    print(
        f"Plan: {bands.total:,} orders over {args.days} days · {units:,} unit codes · "
        f"{retail_n:,} retail identities"
    )

    if not args.skip_generate:
        ch.command(f"DROP DATABASE IF EXISTS {db}")
        ch.command(f"CREATE DATABASE {db}")
        for statement in load_ddl(db):
            ch.command(statement)
        union = " UNION ALL ".join(
            f"SELECT * FROM {db}.sat_order_header__bitrix__{branch}"
            for branch in ("msk", "spb", "ekb", "dxb", "ala")
        )
        ch.command(f"CREATE VIEW {db}.v_order_header_all AS {union}")
        print("Generating…", flush=True)
        started = time.perf_counter()
        stats = generate(ch, db, bands, anchor, retail_n, units, args.chunk)
        generation_wall = time.perf_counter() - started
        print(f"Generation done in {generation_wall:.1f}s")
    else:
        stats = {}
        generation_wall = 0.0

    print("Running analyst queries…", flush=True)
    queries = run_queries(ch, analyst_queries(db, bands), args.query_repeats)
    print("Running correctness checks…", flush=True)
    checks = correctness_checks(ch, db, bands, retail_n, units)
    disk = disk_footprint(ch, db)

    load_rows = sum(s.rows for s in stats.values())
    load_seconds = sum(s.seconds for s in stats.values())
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": db,
        "clickhouse_version": version,
        "days": args.days,
        "anchor": anchor,
        "orders": bands.total,
        "units": units,
        "retail_identities": retail_n,
        "generation_wall_s": generation_wall,
        "load": [
            {
                "table": s.table,
                "rows": s.rows,
                "seconds": round(s.seconds, 3),
                "rows_per_s": round(s.rows_per_s),
            }
            for s in stats.values()
        ],
        "load_total_rows": load_rows,
        "load_total_seconds": round(load_seconds, 3),
        "load_total_rows_per_s": round(load_rows / load_seconds) if load_seconds else 0,
        "queries": queries,
        "checks": checks,
        "disk": disk,
        "total_rows": sum(int(d["rows"]) for d in disk),
        "total_compressed_bytes": sum(int(d["compressed"]) for d in disk),
        "total_uncompressed_bytes": sum(int(d["uncompressed"]) for d in disk),
    }

    markdown = render_markdown(report)
    if args.report_json:
        Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.report_md:
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text(markdown, encoding="utf-8")
    print(markdown)

    if args.drop_after:
        ch.command(f"DROP DATABASE IF EXISTS {db}")
        print(f"Dropped {db}")

    failed = [check for check in checks if not check["passed"]]
    if failed:
        print(f"\n{len(failed)} correctness check(s) FAILED", file=sys.stderr)
        return 2
    print("\nAll correctness checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
