from __future__ import annotations

import argparse
import os
import sys

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rotate AgentFlow API keys without downtime.")
    parser.add_argument("--base-url", default=os.getenv("AGENTFLOW_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--admin-key", default=os.getenv("AGENTFLOW_ADMIN_KEY"))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--revoke-old", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser


def _headers(admin_key: str | None) -> dict[str, str]:
    if not admin_key:
        raise ValueError("Admin key is required. Pass --admin-key or set AGENTFLOW_ADMIN_KEY.")
    return {"X-Admin-Key": admin_key}


def main() -> int:
    args = build_parser().parse_args()
    if args.revoke_old and args.status:
        print("Choose only one action: --revoke-old or --status.", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    key_id = args.key_id
    headers = _headers(args.admin_key)

    try:
        with httpx.Client(timeout=args.timeout) as client:
            if args.status:
                response = client.get(
                    f"{base_url}/v1/admin/keys/{key_id}/rotation-status",
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                print(f"Phase: {payload['phase']}")
                print(f"Old key active until: {payload['old_key_active_until']}")
                print(
                    "Requests on old key last hour: "
                    f"{payload['requests_on_old_key_last_hour']}"
                )
                return 0

            if args.revoke_old:
                response = client.post(
                    f"{base_url}/v1/admin/keys/{key_id}/revoke-old",
                    headers=headers,
                )
                response.raise_for_status()
                print("Old key revoked.")
                return 0

            response = client.post(
                f"{base_url}/v1/admin/keys/{key_id}/rotate",
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            print(f"New key (shown once): {payload['new_key']}")
            print(f"Old key remains active until: {payload['expires_at']}")
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        print(
            f"Rotation request failed with status {exc.response.status_code}: {detail}",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPError as exc:
        print(f"Rotation request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
