from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta

import duckdb

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None

from src.serving.api.security import hash_api_key

from .manager import ApiKeysConfig, AuthManager, KeyCreateRequest, TenantKey


class KeyRotator:
    def __init__(self, manager: AuthManager) -> None:
        self._manager = manager

    def list_keys_with_usage(self) -> list[dict]:
        stats = self._usage_by_key()
        old_key_stats = self.old_key_usage_by_key_id()
        items = []
        sorted_keys = sorted(
            self._manager._loaded_keys or list(self._manager.keys_by_value.values()),
            key=lambda value: (value.tenant, value.name),
        )
        for item in sorted_keys:
            # Plaintext key material is intentionally NOT exposed here. It is
            # returned only once at create/rotate time. Listing it would let
            # anyone with admin access recover active tenant keys (Codex audit
            # p2_1 #7).
            items.append(
                {
                    "key_id": item.key_id,
                    "key_hash_present": item.key_hash is not None,
                    "name": item.name,
                    "tenant": item.tenant,
                    "rate_limit_rpm": item.rate_limit_rpm,
                    "allowed_entity_types": item.allowed_entity_types,
                    "created_at": item.created_at.isoformat(),
                    "requests_last_24h": stats.get((item.tenant, item.name), 0),
                    "rotation_phase": self.rotation_phase(item),
                    "old_key_active_until": (
                        item.previous_key_active_until.isoformat()
                        if item.previous_key_active_until is not None
                        else None
                    ),
                    "requests_on_old_key_last_hour": old_key_stats.get(item.key_id or "", 0),
                }
            )
        return items

    def create_key(self, payload: KeyCreateRequest) -> TenantKey:
        with self._manager._config_lock:
            config = self._manager._load_config()
            self.ensure_key_ids(config)
            existing_ids = {item.key_id for item in config.keys if item.key_id is not None}
            key_value = self.generate_key(payload.tenant, payload.name)
            new_key = TenantKey(
                key_id=self.generate_key_id(payload.tenant, payload.name, existing_ids),
                key=key_value,
                key_hash=hash_api_key(
                    key_value,
                    rounds=self._manager.security_policy.bcrypt_rounds,
                ),
                name=payload.name,
                tenant=payload.tenant,
                rate_limit_rpm=payload.rate_limit_rpm,
                allowed_entity_types=payload.allowed_entity_types,
                created_at=datetime.now(UTC).date(),
            )
            self.validate_generated_key(new_key.key)
            config.keys.append(new_key)
            self.write_config(config)
            if new_key.key_hash is not None and new_key.key is not None:
                self._manager._runtime_plaintext_by_hash[new_key.key_hash] = new_key.key
        self._manager.load()
        return new_key

    def revoke_key(self, api_key: str) -> bool:
        with self._manager._config_lock:
            config = self._manager._load_config()
            self.ensure_key_ids(config)
            removed = [
                item for item in config.keys if self._manager._matches_key_material(item, api_key)
            ]
            remaining = [
                item
                for item in config.keys
                if not self._manager._matches_key_material(item, api_key)
            ]
            if len(remaining) == len(config.keys):
                return False
            config.keys = remaining
            self.write_config(config)
            for item in removed:
                if item.key_id is not None:
                    self.cancel_rotation_cleanup_timers(item.key_id)
            self._manager._runtime_plaintext_by_hash = {
                key_hash: key_value
                for key_hash, key_value in self._manager._runtime_plaintext_by_hash.items()
                if key_value != api_key and key_hash != api_key
            }
        self._manager.load()
        return True

    def rotate_key(self, key_id: str) -> tuple[TenantKey, datetime]:
        with self._manager._config_lock:
            config = self._manager._load_config()
            self.ensure_key_ids(config)
            index = self.find_key_index(config, key_id)
            if index is None:
                raise KeyError(key_id)
            item = config.keys[index]
            if self.is_previous_key_active(item):
                raise ValueError("Rotation already in progress.")
            new_key_value = self.generate_key(item.tenant, item.name)
            new_key_hash = hash_api_key(
                new_key_value,
                rounds=self._manager.security_policy.bcrypt_rounds,
            )
            old_key_hash = item.key_hash
            if old_key_hash is None:
                if item.key is None:
                    raise ValueError("Current key material is unavailable for rotation.")
                old_key_hash = hash_api_key(
                    item.key,
                    rounds=self._manager.security_policy.bcrypt_rounds,
                )
            expires_at = datetime.now(UTC) + timedelta(
                seconds=self._manager.rotation_grace_period_seconds
            )
            updated_item = item.model_copy(
                update={
                    "key": new_key_value,
                    "key_hash": new_key_hash,
                    "previous_key_hash": old_key_hash,
                    "previous_key_active_until": expires_at,
                }
            )
            self.validate_generated_key(new_key_value)
            config.keys[index] = updated_item
            self.write_config(config)
            self._manager._runtime_plaintext_by_hash[new_key_hash] = new_key_value
        self._manager.load()
        return self._manager._keys_by_id[key_id].model_copy(
            update={"key": new_key_value}
        ), expires_at

    def revoke_old_key(self, key_id: str) -> bool:
        with self._manager._config_lock:
            config = self._manager._load_config()
            self.ensure_key_ids(config)
            index = self.find_key_index(config, key_id)
            if index is None:
                raise KeyError(key_id)
            item = config.keys[index]
            if item.previous_key_hash is None:
                return False
            config.keys[index] = self.clear_previous_key(item)
            self.write_config(config)
            self.cancel_rotation_cleanup_timers(key_id)
        self._manager.load()
        return True

    def get_rotation_status(self, key_id: str) -> dict[str, object]:
        item = self._manager._keys_by_id.get(key_id)
        if item is None:
            raise KeyError(key_id)
        return {
            "phase": self.rotation_phase(item),
            "old_key_active_until": (
                item.previous_key_active_until.isoformat()
                if item.previous_key_active_until is not None
                else None
            ),
            "requests_on_old_key_last_hour": self.old_key_usage_last_hour(key_id),
        }

    def shutdown(self) -> None:
        with self._manager._config_lock:
            self.cancel_rotation_cleanup_timers()

    def old_key_usage_by_key_id(self) -> dict[str, int]:
        for attempt in range(10):
            try:
                conn = duckdb.connect(str(self._manager.db_path))
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT key_id, COUNT(*) AS requests_last_hour
                    FROM api_usage
                    WHERE key_slot = 'previous'
                      AND ts >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
                      AND key_id IS NOT NULL
                    GROUP BY key_id
                    """
                ).fetchall()
                return dict(rows)
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()
        return {}

    def old_key_usage_last_hour(self, key_id: str) -> int:
        return self.old_key_usage_by_key_id().get(key_id, 0)

    def _usage_by_key(self) -> dict[tuple[str, str], int]:
        for attempt in range(10):
            try:
                conn = duckdb.connect(str(self._manager.db_path))
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT tenant, key_name, COUNT(*) AS requests_last_24h
                    FROM api_usage
                    WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    GROUP BY tenant, key_name
                    """
                ).fetchall()
                return {
                    (tenant, key_name): requests_last_24h
                    for tenant, key_name, requests_last_24h in rows
                }
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()
        return {}

    def write_config(self, config: ApiKeysConfig) -> None:
        if self._manager.api_keys_path is None:
            raise RuntimeError("AGENTFLOW_API_KEYS_FILE must be configured for key management.")
        self._manager.api_keys_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"keys": [self._storage_payload(item) for item in config.keys]}
        if yaml is not None:
            content = yaml.safe_dump(payload, sort_keys=False)
        else:  # pragma: no cover
            content = json.dumps(payload, indent=2)
        self._manager.api_keys_path.write_text(content, encoding="utf-8", newline="\n")

    def generate_key(self, tenant: str, name: str) -> str:
        tenant_slug = re.sub(r"[^a-z0-9]+", "-", tenant.lower()).strip("-") or "tenant"
        name_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"
        # 256 bits of random material (token_urlsafe(32) -> 43 chars).
        # token_hex(4) gave only 32 bits — feasible to brute-force when the
        # tenant/name slug is known (Codex audit p2_2 #3).
        while True:
            candidate = f"af-prod-{tenant_slug}-{name_slug}-{secrets.token_urlsafe(32)}"
            if candidate not in self._manager.keys_by_value:
                return candidate

    def generate_key_id(
        self,
        tenant: str,
        name: str,
        existing_ids: set[str] | None = None,
    ) -> str:
        tenant_slug = re.sub(r"[^a-z0-9]+", "-", tenant.lower()).strip("-") or "tenant"
        name_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"
        seen_ids = set(existing_ids or ())
        while True:
            candidate = f"{tenant_slug}-{name_slug}-{secrets.token_hex(4)}"
            if candidate not in seen_ids:
                return candidate

    def ensure_key_ids(self, config: ApiKeysConfig) -> bool:
        existing_ids = {item.key_id for item in config.keys if item.key_id is not None}
        changed = False
        for index, item in enumerate(config.keys):
            if item.key_id is not None:
                continue
            key_id = self.generate_key_id(item.tenant, item.name, existing_ids)
            existing_ids.add(key_id)
            config.keys[index] = item.model_copy(update={"key_id": key_id})
            changed = True
        return changed

    def find_key_index(self, config: ApiKeysConfig, key_id: str) -> int | None:
        for index, item in enumerate(config.keys):
            if item.key_id == key_id:
                return index
        return None

    def rotation_phase(self, item: TenantKey) -> str:
        return "grace_period" if self.is_previous_key_active(item) else "idle"

    def is_previous_key_active(self, item: TenantKey) -> bool:
        return (
            item.previous_key_hash is not None
            and item.previous_key_active_until is not None
            and item.previous_key_active_until > datetime.now(UTC)
        )

    def clear_previous_key(self, item: TenantKey) -> TenantKey:
        return item.model_copy(
            update={
                "previous_key_hash": None,
                "previous_key_active_until": None,
            }
        )

    def cleanup_expired_rotations(self, config: ApiKeysConfig) -> bool:
        changed = False
        now = datetime.now(UTC)
        for index, item in enumerate(config.keys):
            if (
                item.previous_key_hash is not None
                and item.previous_key_active_until is not None
                and item.previous_key_active_until <= now
            ):
                config.keys[index] = self.clear_previous_key(item)
                changed = True
        return changed

    def schedule_rotation_cleanup(self, item: TenantKey) -> None:
        if item.key_id is None or item.previous_key_active_until is None:
            return
        delay = (item.previous_key_active_until - datetime.now(UTC)).total_seconds()
        if delay <= 0:
            return
        self.cancel_rotation_cleanup_timers(item.key_id)
        timer = threading.Timer(delay, self.expire_previous_key, args=(item.key_id,))
        timer.daemon = True
        self._manager._rotation_cleanup_timers[item.key_id] = timer
        timer.start()

    def expire_previous_key(self, key_id: str) -> None:
        try:
            self.revoke_old_key(key_id)
        except KeyError:
            return
        except Exception as exc:
            from src.serving.api import auth as auth_package

            auth_package.logger.warning(
                "api_key_rotation_cleanup_failed",
                key_id=key_id,
                error=str(exc),
            )

    def cancel_rotation_cleanup_timers(self, key_id: str | None = None) -> None:
        if key_id is not None:
            timer = self._manager._rotation_cleanup_timers.pop(key_id, None)
            if timer is not None:
                timer.cancel()
            return
        timers = list(self._manager._rotation_cleanup_timers.values())
        self._manager._rotation_cleanup_timers.clear()
        for timer in timers:
            timer.cancel()

    def validate_generated_key(self, api_key: str | None) -> None:
        if api_key is None:
            return
        if len(api_key) < self._manager.security_policy.min_key_length:
            raise ValueError(
                f"Generated API key length {len(api_key)} is below "
                f"min_key_length={self._manager.security_policy.min_key_length}."
            )

    def _storage_payload(self, item: TenantKey) -> dict:
        payload = item.model_dump(mode="json", exclude_none=True)
        if "key_hash" in payload:
            payload.pop("key", None)
        return payload


def rotate_all_keys(manager: AuthManager) -> list[tuple[TenantKey, datetime]]:
    rotated: list[tuple[TenantKey, datetime]] = []
    for item in manager.list_keys_with_usage():
        key_id = item["key_id"]
        if key_id is None:
            continue
        rotated.append(manager.rotate_key(key_id))
    return rotated
