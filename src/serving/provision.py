"""Out-of-band provisioning for the serving store.

The API process does not create or seed the external serving store. A serving
identity should not need CREATE/ALTER/INSERT; several booting replicas should
not race each other to seed the same empty table; and a production store should
not be handed demo rows just because it happened to be empty. Boot used to do
all three (audit P0-2). This module is the step that replaces it, made explicit
and runnable on its own — from an operator shell, a Kubernetes Job, or the demo
bring-up.

    python -m src.serving.provision --schema         # idempotent DDL
    python -m src.serving.provision --seed           # demo rows, only if empty
    python -m src.serving.provision --schema --seed  # full demo bring-up

The target is whatever ``SERVING_BACKEND``/``config/serving.yaml`` selects, so
the same command provisions the ClickHouse profile and the file-backed DuckDB
profile. Both operations are idempotent: re-running is a no-op, and ``--seed``
returns without writing when the store already holds orders.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import structlog

from src.serving.backends import ServingBackend, create_backend
from src.serving.backends.duckdb_backend import DuckDBBackend

logger = structlog.get_logger()


def provision(
    *,
    schema: bool,
    seed: bool,
    config_path: str | None = None,
) -> int:
    db_path = os.getenv("DUCKDB_PATH", ":memory:") or ":memory:"
    embedded = DuckDBBackend(db_path=db_path)
    try:
        selected: ServingBackend = create_backend(
            duckdb_backend=embedded,
            config_path=config_path,
        )
        external = selected if selected.name != embedded.name else None

        # Provision every store the API will read. On the ClickHouse profile
        # that is two: the serving tables live in ClickHouse, but the embedded
        # DuckDB still carries control-plane state the API serves (the
        # exception inbox), so a durable DUCKDB_PATH needs its schema too.
        targets: list[ServingBackend] = []
        if db_path != ":memory:":
            targets.append(embedded)
        if external is not None:
            targets.append(external)

        if not targets:
            # Everything configured is in-memory: it would be created and
            # destroyed inside this CLI process. Failing loudly beats a green
            # exit code that provisioned nothing.
            logger.error(
                "provision_has_no_durable_target",
                hint="set DUCKDB_PATH to a file, or SERVING_BACKEND to an external store",
            )
            return 2

        for target in targets:
            if schema:
                target.ensure_schema()
                logger.info("provision_schema_applied", backend=target.name)
            if seed:
                target.seed_demo_data()
                logger.info("provision_demo_seed_applied", backend=target.name)

        return 0
    finally:
        # Release the DuckDB file lock so the next process — the API, a test —
        # can open the store we just provisioned.
        embedded.connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.serving.provision",
        description="Create and optionally seed the configured serving store.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="apply the idempotent serving DDL",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="insert the canonical demo rows, and only when the store is empty",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to serving.yaml (defaults to AGENTFLOW_SERVING_CONFIG)",
    )
    args = parser.parse_args(argv)

    if not args.schema and not args.seed:
        parser.error("nothing to do: pass --schema, --seed, or both")

    return provision(schema=args.schema, seed=args.seed, config_path=args.config)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
