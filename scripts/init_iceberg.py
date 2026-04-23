from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.processing.iceberg_sink import IcebergSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create AgentFlow Iceberg tables.")
    parser.add_argument("--config", default="config/iceberg.yaml")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sink = IcebergSink(config_path=args.config)
    sink.create_tables_if_not_exist()
    print(f"Initialized {len(sink.table_configs)} Iceberg tables in namespace {sink.namespace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
