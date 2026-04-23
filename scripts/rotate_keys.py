from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.serving.api.auth import AuthManager, KeyCreateRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an API key and store only its bcrypt hash.")
    parser.add_argument("--api-keys", default="config/api_keys.yaml")
    parser.add_argument("--security-config", default="config/security.yaml")
    parser.add_argument("--name", default="Rotated Key")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--rate-limit-rpm", type=int, default=120)
    parser.add_argument("--allowed-entity-types", nargs="*", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manager = AuthManager(
        api_keys_path=Path(args.api_keys),
        security_config_path=Path(args.security_config),
    )
    manager.load()
    created = manager.create_key(
        KeyCreateRequest(
            name=args.name,
            tenant=args.tenant,
            rate_limit_rpm=args.rate_limit_rpm,
            allowed_entity_types=args.allowed_entity_types,
        )
    )
    print(f"Plaintext API key (shown once): {created.key}")
    print(f"Stored bcrypt hash in {Path(args.api_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
