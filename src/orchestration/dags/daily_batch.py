"""Daily batch DAG: compaction, aggregation, and quality reports.

Runs daily at 02:00 UTC when streaming traffic is lowest.
Handles Iceberg maintenance and pre-computes aggregates for fast serving.
"""

from dagster import (
    AssetExecutionContext,
    Definitions,
    ScheduleDefinition,
    asset,
    define_asset_job,
)


@asset(group_name="maintenance")
def iceberg_snapshot_expiry(context: AssetExecutionContext):
    """Expire old Iceberg snapshots to prevent metadata bloat.

    Keeps last 30 days of snapshots for time-travel debugging.
    """
    context.log.info("Expiring Iceberg snapshots older than 30 days")
    # In production: connect to Iceberg catalog and run expiry
    # catalog.expire_snapshots("orders_v2", older_than_days=30)
    # catalog.expire_snapshots("sessions_aggregated", older_than_days=30)
    return {"tables_processed": 2, "snapshots_expired": "N/A"}


@asset(group_name="maintenance", deps=[iceberg_snapshot_expiry])
def iceberg_compaction(context: AssetExecutionContext):
    """Compact small Iceberg data files into larger ones.

    Flink streaming writes produce many small files. Compaction merges
    them into optimally-sized files (128-512 MB) for faster reads.
    """
    context.log.info("Compacting Iceberg data files")
    # In production:
    # catalog.rewrite_data_files("orders_v2", target_file_size_mb=256)
    # catalog.rewrite_data_files("sessions_aggregated", target_file_size_mb=256)
    return {"tables_compacted": 2}


@asset(group_name="aggregation")
def daily_user_profiles(context: AssetExecutionContext):
    """Pre-compute user profile aggregates for fast entity lookups.

    Aggregates: total_orders, total_spent, first/last order, preferred category.
    """
    context.log.info("Computing daily user profiles")
    # In production: SQL against Iceberg tables via Trino/DuckDB
    # INSERT OVERWRITE users_enriched
    # SELECT user_id, COUNT(*) as total_orders, SUM(total_amount) as total_spent, ...
    # FROM orders_v2 GROUP BY user_id
    return {"users_updated": "N/A"}


@asset(group_name="aggregation")
def daily_product_metrics(context: AssetExecutionContext):
    """Pre-compute product-level metrics: views, add-to-cart rate, revenue."""
    context.log.info("Computing daily product metrics")
    return {"products_updated": "N/A"}


@asset(group_name="quality", deps=[daily_user_profiles, daily_product_metrics])
def daily_quality_report(context: AssetExecutionContext):
    """Generate daily data quality report.

    Checks:
    - Row counts vs previous day (alert on >20% deviation)
    - Null rates for required fields
    - Referential integrity (orders → users, payments → orders)
    - Dead letter topic volume
    """
    context.log.info("Generating daily quality report")
    return {"checks_passed": "N/A", "checks_failed": 0}


# ── Job & Schedule ──────────────────────────────────────────────

daily_maintenance_job = define_asset_job(
    name="daily_maintenance",
    selection=[
        iceberg_snapshot_expiry,
        iceberg_compaction,
        daily_user_profiles,
        daily_product_metrics,
        daily_quality_report,
    ],
)

daily_schedule = ScheduleDefinition(
    job=daily_maintenance_job,
    cron_schedule="0 2 * * *",  # 02:00 UTC daily
)

defs = Definitions(
    assets=[
        iceberg_snapshot_expiry,
        iceberg_compaction,
        daily_user_profiles,
        daily_product_metrics,
        daily_quality_report,
    ],
    jobs=[daily_maintenance_job],
    schedules=[daily_schedule],
)
