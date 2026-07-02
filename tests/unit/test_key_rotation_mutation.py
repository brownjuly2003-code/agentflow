"""Narrow, duckdb-free mutation test for the API-key rotation lifecycle
(src/serving/api/auth/key_rotation.py).

This is the test the mutation gate runs against ``serving/api/auth/key_rotation.py``
(see scripts/mutation_report.py MODULE_TARGETS). key_rotation.py is the
create / rotate / revoke / revoke-old surface plus the rotation-grace state
machine: a surviving mutant here is a key that fails to rotate, an old key that
outlives its grace window, a revoke that does not actually remove material, a
generated key persisted with its plaintext, or a key hashed with the wrong
cost/scheme. The same security-critical class the HTTP admin endpoints in
tests/integration/test_rotation.py drive end to end.

Design rules, shared with test_auth_manager_mutation.py /
test_rate_limiter_mutation.py / test_sql_builder_mutation.py (see
fable_handoff.md cont.16-23):

1. **duckdb-free.** Importing ``serving.api.auth.key_rotation`` runs the auth
   package ``__init__`` (``import duckdb``) and, since ADR 0010 slice 4,
   ``key_rotation`` -> ``manager`` -> ``control_plane`` -> ``embedded`` pulls in
   ``import duckdb`` there instead (key_rotation itself no longer imports
   duckdb directly — its usage-stat methods delegate to
   ``AuthManager.store``). Real duckdb's lazy ``_duckdb._sqltypes`` import
   crashes mutmut's coverage-instrumented stats pass (the same break ci.yml
   works around with ``coverage run``). A fake top-level ``duckdb`` module
   satisfies the import chain either way; the three usage-stat
   methods that actually *call* duckdb (``old_key_usage_by_key_id`` /
   ``_usage_by_key`` / ``old_key_usage_last_hour``) are stubbed on the rotator in
   the tests that need them, so their bodies stay uncovered and are NOT mutated.
   Those duckdb-querying observability methods (not an auth boundary; their SQL
   string literals are unkillable without a real duckdb to execute them) are
   pinned instead by the real-duckdb retry tests in tests/unit/test_key_rotation.py.

2. **The two ``while True`` uniqueness loops (``generate_key`` /
   ``generate_key_id``) are deliberately left uncovered.** mutmut flips
   ``not in`` -> ``in`` (node_mutation._keyword_mapping), which turns
   ``while True: candidate = ...; if candidate not in seen: return`` into an
   infinite loop -> a *timeout* mutant, and scripts/mutation_report.py counts a
   timeout as a hard violation, not a survivor. There is no per-line mutmut
   ignore in this version, and refactoring security-relevant key generation just
   to satisfy the tool is the wrong trade. So both generators are stubbed in the
   create / rotate / ensure_key_ids tests (their bodies never execute -> never
   mutated), and their slug + 256-bit entropy + collision behaviour is pinned by
   tests/unit/test_key_rotation.py (``af-prod-`` prefix, real ``token_urlsafe``).
   The stubs RECORD their args so a mutant that passes the wrong tenant/name/
   existing-id set to a generator is still killed. To keep ``AuthManager.load()``
   -> ``ensure_key_ids`` from calling the real ``generate_key_id`` (which would
   re-cover the loop), every seed key carries a ``key_id``.

3. **No fixtures for the subject -- inline construction + direct method calls.**
   With ``mutate_only_covered_lines = true`` a fixture-built object leaves method
   lines uncovered (only ``__init__`` mutated). The rotator methods under test
   are called directly so coverage attributes every line.

4. **Workspace discrimination by top-level ``serving``.** mutmut's mutants/
   workspace copies src/serving to a TOP-LEVEL ``serving`` package; ordinary
   pytest has no top-level ``serving`` (only src.serving). Gate the harness stubs
   on ``find_spec("serving")`` -- NOT ``import src``, which stays importable via
   the editable install even inside the workspace.

5. **No real timers.** ``threading.Timer`` is replaced with a record-only fake so
   ``schedule_rotation_cleanup`` (reached via ``load()`` after a rotation) never
   spawns a background thread across the hundreds of per-mutant runs, and so the
   timer wiring (delay / callback / args) can be asserted.

Residual survivors are genuine EQUIVALENT mutants, documented so the honest 0.90
threshold is defensible: strict-vs-nonstrict comparisons against the live
``datetime.now(UTC)`` wall clock (``is_previous_key_active`` ``>`` vs ``>=``,
``cleanup_expired_rotations`` / ``schedule_rotation_cleanup`` ``<=`` boundaries --
only differ at an unreachable exact-equality instant); ``datetime.now(UTC)`` vs
``datetime.now(None)`` (identical date on a UTC runner); the ``revoke_key``
runtime-cache prune clauses (subsumed by ``load()``'s live-hash reprune); the
``updated_item`` ``"key"`` field in ``rotate_key`` (stripped by ``_storage_payload``
on persist and overwritten by the final ``model_copy`` on return); and
``write_text`` ``encoding`` / ``newline`` kwargs (no observable change on a
UTF-8 / ``\\n`` platform).
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, date, datetime, timedelta


def _in_mutation_workspace() -> bool:
    # mutmut's mutants/ workspace copies src/serving to a TOP-LEVEL `serving`
    # package (scripts/mutation_report.py prepare_workspace); ordinary pytest has
    # no top-level `serving` (only src.serving), so its presence cleanly marks the
    # harness. `import src` does NOT discriminate: the editable install keeps the
    # real `src` importable even inside the workspace.
    import importlib.util

    try:
        return importlib.util.find_spec("serving") is not None
    except (ImportError, ValueError):
        return False


def _install_harness_stubs() -> None:
    # The auth package import chain (auth/__init__.py `import duckdb`;
    # key_rotation `import duckdb` + `from ...duckdb_connection import
    # connect_duckdb`) pulls duckdb at import time. Replace the whole `duckdb`
    # module with a fake supplying the names referenced at import / type-check
    # time. The methods that genuinely execute a duckdb call are stubbed per-test
    # (see module docstring), so the fake changes no mutated logic; it only keeps
    # the import chain off real duckdb's coverage-breaking native extension.
    # Force-overwrite (not setdefault) so a duckdb already pulled in by the
    # coverage harness can't shadow the fake.
    duckdb_stub = types.ModuleType("duckdb")

    class _DuckDBError(Exception):
        pass

    duckdb_stub.Error = _DuckDBError
    duckdb_stub.IOException = type("IOException", (_DuckDBError,), {})
    duckdb_stub.DuckDBPyConnection = object

    def _connect(*_args: object, **_kwargs: object) -> object:
        raise _DuckDBError("duckdb is stubbed out in the mutation harness")

    duckdb_stub.connect = _connect
    sys.modules["duckdb"] = duckdb_stub


if _in_mutation_workspace():
    _install_harness_stubs()

try:  # mutation-harness workspace exposes these as a top-level package
    from serving.api.auth import key_rotation as kr
    from serving.api.auth.manager import ApiKeysConfig, AuthManager, KeyCreateRequest, TenantKey
except ImportError:  # ordinary pytest sees them under the src package
    from src.serving.api.auth import key_rotation as kr
    from src.serving.api.auth.manager import ApiKeysConfig, AuthManager, KeyCreateRequest, TenantKey

import pytest

rotate_all_keys = kr.rotate_all_keys

SEED_KEY_YAML = (
    "keys:\n"
    '  - key_id: "acme-rotation-agent-aaaa1111"\n'
    '    key: "rotation-acme-key"\n'
    '    name: "Rotation Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 100\n"
    '    created_at: "2026-04-10"\n'
)
SEED_KEY_ID = "acme-rotation-agent-aaaa1111"


# --------------------------------------------------------------------------- #
# Record-only Timer + fast, recording hash/lookup/generator fakes.
# --------------------------------------------------------------------------- #


class _FakeTimer:
    def __init__(self, delay: float, function: object, args: object = ()) -> None:
        self.delay = delay
        self.function = function
        self.args = args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def _rec_hash(calls: list) -> object:
    # Fast, deterministic stand-in for hash_api_key that RECORDS (value, rounds,
    # scheme). Encoding the value lets the hash track the key actually passed;
    # recording rounds/scheme kills a mutant that drops/nulls the cost factor or
    # hashing scheme (a real downgrade of the at-rest key protection).
    def _h(value: str, rounds: object = None, scheme: object = None) -> str:
        calls.append((value, rounds, scheme))
        return f"hash::{value}"

    return _h


def _rec_lookup(calls: list | None = None) -> object:
    def _l(value: str) -> str:
        if calls is not None:
            calls.append(value)
        return f"lk::{value}"

    return _l


def _rec_gen(calls: list, ret: str) -> object:
    def _g(tenant: str, name: str) -> str:
        calls.append((tenant, name))
        return ret

    return _g


def _rec_gen_id(calls: list, rets: list[str]) -> object:
    it = iter(rets)

    def _g(tenant: str, name: str, existing_ids: object = None) -> str:
        snapshot = set(existing_ids) if existing_ids is not None else None
        calls.append((tenant, name, snapshot))
        return next(it)

    return _g


def _build_manager(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    grace: int = 300,
    seed: str = SEED_KEY_YAML,
) -> AuthManager:
    monkeypatch.setattr(kr.threading, "Timer", _FakeTimer)
    monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
    api_keys_path = tmp_path / "config" / "api_keys.yaml"  # type: ignore[operator]
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(seed, encoding="utf-8", newline="\n")
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=tmp_path / "usage.duckdb",  # type: ignore[operator]
        admin_key="admin-secret",
    )
    manager.security_policy.bcrypt_rounds = 4
    manager.rotation_grace_period_seconds = grace
    manager.load()
    return manager


def _tk(**overrides: object) -> TenantKey:
    base: dict[str, object] = {
        "key": "plain-key",
        "name": "n",
        "tenant": "acme",
        "created_at": date(2026, 1, 1),
    }
    base.update(overrides)
    return TenantKey(**base)  # type: ignore[arg-type]


def _assert_hash_uses_policy(calls: list, manager: AuthManager) -> None:
    # Every hash_api_key call must carry the configured cost + scheme; a dropped
    # or nulled rounds/scheme kwarg is a real downgrade.
    assert calls
    for _value, rounds, scheme in calls:
        assert rounds == manager.security_policy.bcrypt_rounds
        assert scheme == manager.security_policy.key_hashing


# --------------------------------------------------------------------------- #
# create_key
# --------------------------------------------------------------------------- #


class TestCreateKey:
    def test_create_key_populates_every_field_and_persists_without_plaintext(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator
        gen_calls: list = []
        id_calls: list = []
        hash_calls: list = []
        lookup_calls: list = []
        new_key = "af-prod-beta-reporting-" + "z" * 43

        monkeypatch.setattr(rotator, "generate_key", _rec_gen(gen_calls, new_key))
        monkeypatch.setattr(
            rotator, "generate_key_id", _rec_gen_id(id_calls, ["beta-reporting-dead"])
        )
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash(hash_calls))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup(lookup_calls))

        created = rotator.create_key(
            KeyCreateRequest(
                name="Reporting", tenant="beta", rate_limit_rpm=50, allowed_entity_types=["order"]
            )
        )

        # generate_key / generate_key_id received the request's tenant+name, and
        # generate_key_id received the existing-id set (the seed's id), not None.
        assert gen_calls == [("beta", "Reporting")]
        assert id_calls == [("beta", "Reporting", {SEED_KEY_ID})]
        # hashed/looked-up the NEWLY generated key with the configured cost/scheme.
        assert hash_calls == [
            (new_key, manager.security_policy.bcrypt_rounds, manager.security_policy.key_hashing)
        ]
        assert lookup_calls == [new_key]
        # Every field flows from the request / generated material.
        assert created.key == new_key
        assert created.key_id == "beta-reporting-dead"
        assert created.key_hash == f"hash::{new_key}"
        assert created.key_lookup == f"lk::{new_key}"
        assert created.name == "Reporting"
        assert created.tenant == "beta"
        assert created.rate_limit_rpm == 50
        assert created.allowed_entity_types == ["order"]
        assert created.created_at == datetime.now(UTC).date()
        # Cached plaintext binding keyed by the new hash.
        assert manager._runtime_plaintext_by_hash[created.key_hash] == new_key
        # Persisted (reload indexed it) and the plaintext was stripped on disk.
        assert created.key_id in manager._keys_by_id
        import yaml

        on_disk = yaml.safe_load(manager.api_keys_path.read_text(encoding="utf-8"))
        entry = next(k for k in on_disk["keys"] if k["key_id"] == "beta-reporting-dead")
        assert entry["key_hash"] == f"hash::{new_key}"
        assert "key" not in entry  # never persist plaintext for a hashed key

    def test_create_key_validates_generated_key_length(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # create_key must run validate_generated_key on the generated key; a
        # mutant that validates None instead would let a too-short key through.
        rotator = manager._key_rotator
        manager.security_policy.min_key_length = 100
        monkeypatch.setattr(rotator, "generate_key", lambda tenant, name: "too-short")
        monkeypatch.setattr(rotator, "generate_key_id", lambda *a, **k: "beta-x-0001")
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())
        with pytest.raises(ValueError, match="below min_key_length"):
            rotator.create_key(KeyCreateRequest(name="X", tenant="beta"))


# --------------------------------------------------------------------------- #
# rotate_key
# --------------------------------------------------------------------------- #


class TestRotateKey:
    def test_rotate_plaintext_key_hashes_old_material_and_opens_grace(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator
        gen_calls: list = []
        hash_calls: list = []
        new_key = "af-prod-acme-rotation-agent-" + "y" * 43
        monkeypatch.setattr(rotator, "generate_key", _rec_gen(gen_calls, new_key))
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash(hash_calls))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())

        before = datetime.now(UTC)
        rotated, expires_at = manager.rotate_key(SEED_KEY_ID)
        after = datetime.now(UTC)

        assert rotated.key == new_key
        # generate_key got the rotated key's own tenant/name.
        assert gen_calls == [("acme", "Rotation Agent")]
        # Both the new-key hash and the on-the-fly old-key hash carry the policy
        # cost + scheme (the seed is PLAINTEXT-only, so the old material is hashed
        # via the `old_key_hash is None` fallback branch).
        _assert_hash_uses_policy(hash_calls, manager)
        assert {c[0] for c in hash_calls} == {new_key, "rotation-acme-key"}
        stored = manager._keys_by_id[SEED_KEY_ID]
        assert stored.key_hash == f"hash::{new_key}"
        assert stored.key_lookup == f"lk::{new_key}"
        assert stored.previous_key_hash == "hash::rotation-acme-key"
        assert stored.previous_key_lookup == "lk::rotation-acme-key"
        # expires_at == now + grace (300s); pins the timedelta sign + seconds.
        assert before + timedelta(seconds=300) <= expires_at <= after + timedelta(seconds=300)
        # The new plaintext is cached under the new hash (survives load()'s reprune).
        assert manager._runtime_plaintext_by_hash[f"hash::{new_key}"] == new_key
        assert rotator.is_previous_key_active(stored) is True
        assert rotator.rotation_phase(stored) == "grace_period"

    def test_rotate_existing_hash_keeps_stored_hash_as_previous(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A key that already carries a hash takes the non-fallback branch:
        # old_key_hash = item.key_hash directly (no re-hash of plaintext).
        seed = (
            "keys:\n"
            '  - key_id: "acme-hashed-agent-bbbb2222"\n'
            '    key_hash: "stored-current-hash"\n'
            '    key_lookup: "stored-current-lk"\n'
            '    name: "Hashed Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            '    created_at: "2026-04-10"\n'
        )
        manager = _build_manager(tmp_path, monkeypatch, seed=seed)
        try:
            rotator = manager._key_rotator
            new_key = "af-prod-acme-hashed-agent-" + "x" * 43
            monkeypatch.setattr(rotator, "generate_key", lambda tenant, name: new_key)
            monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
            monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())

            manager.rotate_key("acme-hashed-agent-bbbb2222")

            stored = manager._keys_by_id["acme-hashed-agent-bbbb2222"]
            assert stored.previous_key_hash == "stored-current-hash"  # not re-hashed
            assert stored.previous_key_lookup == "stored-current-lk"
        finally:
            manager.shutdown()

    def test_rotate_validates_generated_key_length(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # rotate_key must validate the freshly generated key; a mutant validating
        # None would let a too-short rotated key through.
        rotator = manager._key_rotator
        manager.security_policy.min_key_length = 100
        monkeypatch.setattr(rotator, "generate_key", lambda tenant, name: "too-short")
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())
        with pytest.raises(ValueError, match="below min_key_length"):
            manager.rotate_key(SEED_KEY_ID)

    def test_rotate_unknown_key_id_raises_with_that_id(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        monkeypatch.setattr(manager._key_rotator, "generate_key", lambda tenant, name: "x" * 50)
        # The KeyError must name the missing id (a KeyError(None) mutant is killed).
        with pytest.raises(KeyError, match="does-not-exist"):
            manager.rotate_key("does-not-exist")

    def test_rotate_twice_rejects_overlap(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator
        monkeypatch.setattr(
            rotator, "generate_key", lambda tenant, name: "af-prod-acme-rotation-agent-" + "y" * 43
        )
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())
        manager.rotate_key(SEED_KEY_ID)
        # Anchored so an XX-wrapped / re-cased message mutant is killed.
        with pytest.raises(ValueError, match=r"^Rotation already in progress\.$"):
            manager.rotate_key(SEED_KEY_ID)


# --------------------------------------------------------------------------- #
# revoke_key
# --------------------------------------------------------------------------- #


class TestRevokeKey:
    def test_revoke_known_plaintext_removes_it(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        assert manager.revoke_key("rotation-acme-key") is True
        assert "rotation-acme-key" not in manager.keys_by_value
        assert manager.configured_key_count == 0

    def test_revoke_unknown_returns_false(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # remaining == all keys -> nothing matched -> False, config untouched.
        assert manager.revoke_key("not-a-real-key") is False
        assert manager.configured_key_count == 1

    def test_revoke_clears_cached_material_for_the_removed_key(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # Revoking a key must not leave its plaintext lingering in the runtime
        # cache. (revoke_key's own value/hash prune is belt-and-suspenders that
        # load()'s live-hash reprune subsumes -- those filter clauses are
        # equivalent mutants; this pins the observable contract.)
        manager._runtime_plaintext_by_hash = {"some-hash": "rotation-acme-key"}
        assert manager.revoke_key("rotation-acme-key") is True
        assert manager.configured_key_count == 0
        assert manager._runtime_plaintext_by_hash == {}

    def test_revoke_cancels_the_removed_keys_cleanup_timer(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # A revoked key with a scheduled rotation-cleanup timer must have that
        # timer cancelled by id (kills the `is None` branch flip and the
        # cancel(None) arg mutant).
        timer = _FakeTimer(300, None)
        manager._rotation_cleanup_timers[SEED_KEY_ID] = timer
        assert manager.revoke_key("rotation-acme-key") is True
        assert timer.cancelled is True
        assert SEED_KEY_ID not in manager._rotation_cleanup_timers


# --------------------------------------------------------------------------- #
# revoke_old_key
# --------------------------------------------------------------------------- #


class TestRevokeOldKey:
    def test_revoke_old_key_ends_grace_and_cancels_timer(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator
        monkeypatch.setattr(
            rotator, "generate_key", lambda tenant, name: "af-prod-acme-rotation-agent-" + "y" * 43
        )
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())
        manager.rotate_key(SEED_KEY_ID)
        # Plant a cleanup timer so the cancel-by-id call is observable.
        timer = _FakeTimer(300, None)
        manager._rotation_cleanup_timers[SEED_KEY_ID] = timer

        assert manager.revoke_old_key(SEED_KEY_ID) is True
        stored = manager._keys_by_id[SEED_KEY_ID]
        assert stored.previous_key_hash is None
        assert rotator.rotation_phase(stored) == "idle"
        assert timer.cancelled is True  # cancel(key_id), not cancel(None)

    def test_revoke_old_key_without_rotation_returns_false(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # previous_key_hash is None -> the early `return False` branch.
        assert manager.revoke_old_key(SEED_KEY_ID) is False

    def test_revoke_old_key_unknown_raises_with_that_id(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        with pytest.raises(KeyError, match="does-not-exist"):
            manager.revoke_old_key("does-not-exist")


# --------------------------------------------------------------------------- #
# get_rotation_status
# --------------------------------------------------------------------------- #


class TestGetRotationStatus:
    def test_status_idle_uses_key_id_for_usage(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # old_key_usage_last_hour must be called with the requested key_id (a
        # mutant passing None is killed because the stub keys off the id).
        monkeypatch.setattr(
            manager._key_rotator,
            "old_key_usage_last_hour",
            lambda key_id: 7 if key_id == SEED_KEY_ID else -1,
        )
        status = manager.get_rotation_status(SEED_KEY_ID)
        assert status["phase"] == "idle"
        assert status["old_key_active_until"] is None
        assert status["requests_on_old_key_last_hour"] == 7

    def test_status_grace_period_serialises_active_until(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator
        monkeypatch.setattr(
            rotator, "generate_key", lambda tenant, name: "af-prod-acme-rotation-agent-" + "y" * 43
        )
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())
        monkeypatch.setattr(rotator, "old_key_usage_last_hour", lambda key_id: 0)
        _, expires_at = manager.rotate_key(SEED_KEY_ID)

        status = manager.get_rotation_status(SEED_KEY_ID)
        assert status["phase"] == "grace_period"
        assert status["old_key_active_until"] == expires_at.isoformat()

    def test_status_unknown_raises_with_that_id(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        with pytest.raises(KeyError, match="does-not-exist"):
            manager.get_rotation_status("does-not-exist")


# --------------------------------------------------------------------------- #
# list_keys_with_usage  (usage queries stubbed -> their duckdb bodies uncovered)
# --------------------------------------------------------------------------- #


class TestListKeysWithUsage:
    _TWO_KEY_YAML = (
        "keys:\n"
        '  - key_id: "acme-zzz-agent-11112222"\n'
        '    key: "zzz-plain"\n'
        '    name: "Zzz Agent"\n'
        '    tenant: "acme"\n'
        "    rate_limit_rpm: 100\n"
        '    created_at: "2026-04-10"\n'
        '  - key_id: "acme-aaa-agent-33334444"\n'
        '    key_hash: "aaa-hash"\n'
        '    key_lookup: "aaa-lk"\n'
        '    name: "Aaa Agent"\n'
        '    tenant: "acme"\n'
        "    rate_limit_rpm: 50\n"
        '    allowed_entity_types: ["order"]\n'
        '    created_at: "2026-04-11"\n'
    )

    def test_listing_is_sorted_maps_fields_and_omits_plaintext(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch, seed=self._TWO_KEY_YAML)
        try:
            rotator = manager._key_rotator
            monkeypatch.setattr(rotator, "_usage_by_key", lambda: {("acme", "Zzz Agent"): 12})
            monkeypatch.setattr(
                rotator, "old_key_usage_by_key_id", lambda: {"acme-aaa-agent-33334444": 3}
            )

            items = manager.list_keys_with_usage()

            # sorted by (tenant, name): "Aaa Agent" before "Zzz Agent".
            assert [it["name"] for it in items] == ["Aaa Agent", "Zzz Agent"]
            aaa, zzz = items
            # No plaintext key field anywhere.
            assert "key" not in aaa
            assert "key" not in zzz
            # Every documented field is present under its exact name.
            assert aaa["key_id"] == "acme-aaa-agent-33334444"
            assert zzz["key_id"] == "acme-zzz-agent-11112222"
            assert aaa["key_hash_present"] is True  # hashed entry
            assert zzz["key_hash_present"] is False  # plaintext-only entry
            assert aaa["allowed_entity_types"] == ["order"]
            assert zzz["allowed_entity_types"] is None
            # 24h usage keyed by (tenant, name); old-key usage keyed by key_id.
            assert zzz["requests_last_24h"] == 12
            assert aaa["requests_last_24h"] == 0
            assert aaa["requests_on_old_key_last_hour"] == 3
            assert zzz["requests_on_old_key_last_hour"] == 0
            # Field mapping is faithful.
            assert zzz["tenant"] == "acme"
            assert zzz["rate_limit_rpm"] == 100
            assert aaa["rate_limit_rpm"] == 50
            assert zzz["rotation_phase"] == "idle"
            assert zzz["created_at"] == "2026-04-10"
        finally:
            manager.shutdown()

    def test_listing_falls_back_to_keys_by_value_when_loaded_keys_empty(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # When _loaded_keys is falsy the source is list(keys_by_value.values());
        # a mutant that calls list(None) raises here (kills the fallback mutant).
        rotator = manager._key_rotator
        monkeypatch.setattr(rotator, "_usage_by_key", lambda: {})
        monkeypatch.setattr(rotator, "old_key_usage_by_key_id", lambda: {})
        manager._loaded_keys = []
        manager.keys_by_value = {"rotation-acme-key": _tk(key="rotation-acme-key", name="Solo")}
        items = manager.list_keys_with_usage()
        assert [it["name"] for it in items] == ["Solo"]


# --------------------------------------------------------------------------- #
# rotation-grace state helpers
# --------------------------------------------------------------------------- #


class TestPreviousKeyActive:
    def test_inactive_when_no_previous_hash(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(previous_key_active_until=datetime.now(UTC) + timedelta(hours=1))
        assert manager._key_rotator.is_previous_key_active(item) is False

    def test_inactive_when_no_active_until(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(previous_key_hash="prev")
        assert manager._key_rotator.is_previous_key_active(item) is False

    def test_inactive_when_expired(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(
            previous_key_hash="prev",
            previous_key_active_until=datetime.now(UTC) - timedelta(hours=1),
        )
        assert manager._key_rotator.is_previous_key_active(item) is False

    def test_active_when_hash_and_future_until(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(
            previous_key_hash="prev",
            previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
        )
        assert manager._key_rotator.is_previous_key_active(item) is True

    def test_rotation_phase_reflects_active_state(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        active = _tk(
            previous_key_hash="prev",
            previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
        )
        idle = _tk(previous_key_hash=None)
        assert manager._key_rotator.rotation_phase(active) == "grace_period"
        assert manager._key_rotator.rotation_phase(idle) == "idle"


class TestClearPreviousKey:
    def test_clears_all_three_previous_fields(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(
            key_hash="cur",
            previous_key_hash="prev",
            previous_key_lookup="prev-lk",
            previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
        )
        cleared = manager._key_rotator.clear_previous_key(item)
        assert cleared.previous_key_hash is None
        assert cleared.previous_key_lookup is None
        assert cleared.previous_key_active_until is None
        # unrelated fields preserved
        assert cleared.key_hash == "cur"


class TestCleanupExpiredRotations:
    def test_clears_only_expired_previous_keys(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        expired = _tk(
            key_id="x-1",
            key_hash="c1",
            previous_key_hash="p1",
            previous_key_active_until=datetime.now(UTC) - timedelta(hours=1),
        )
        live = _tk(
            key_id="x-2",
            key_hash="c2",
            previous_key_hash="p2",
            previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
        )
        config = ApiKeysConfig(keys=[expired, live])
        changed = manager._key_rotator.cleanup_expired_rotations(config)
        assert changed is True
        assert config.keys[0].previous_key_hash is None  # expired cleared
        assert config.keys[1].previous_key_hash == "p2"  # live untouched

    def test_returns_false_when_nothing_expired(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        live = _tk(
            key_id="x-2",
            key_hash="c2",
            previous_key_hash="p2",
            previous_key_active_until=datetime.now(UTC) + timedelta(hours=1),
        )
        config = ApiKeysConfig(keys=[live])
        assert manager._key_rotator.cleanup_expired_rotations(config) is False


# --------------------------------------------------------------------------- #
# index helpers
# --------------------------------------------------------------------------- #


class TestEnsureKeyIds:
    def test_assigns_ids_to_idless_entries_accumulating_existing(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # generate_key_id is stubbed (its real `while True` loop must stay
        # uncovered) but RECORDS args: each id-less entry is generated with its
        # own tenant/name and an existing-id set that grows as ids are assigned.
        id_calls: list = []
        monkeypatch.setattr(
            manager._key_rotator, "generate_key_id", _rec_gen_id(id_calls, ["gen-1", "gen-2"])
        )
        keyed = _tk(key_id="keep-id", key_hash="h0")
        first = _tk(key_id=None, key_hash="h1", tenant="t1", name="n1")
        second = _tk(key_id=None, key_hash="h2", tenant="t2", name="n2")
        config = ApiKeysConfig(keys=[keyed, first, second])

        changed = manager._key_rotator.ensure_key_ids(config)

        assert changed is True
        assert config.keys[0].key_id == "keep-id"  # untouched
        assert config.keys[1].key_id == "gen-1"
        assert config.keys[2].key_id == "gen-2"
        # tenant/name forwarded correctly; existing-id set seeded with keep-id and
        # then accumulates the freshly assigned gen-1.
        assert id_calls[0] == ("t1", "n1", {"keep-id"})
        assert id_calls[1] == ("t2", "n2", {"keep-id", "gen-1"})

    def test_returns_false_when_all_have_ids(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        called = {"n": 0}

        def _boom(*_a: object, **_k: object) -> str:
            called["n"] += 1
            return "never"

        monkeypatch.setattr(manager._key_rotator, "generate_key_id", _boom)
        config = ApiKeysConfig(keys=[_tk(key_id="a", key_hash="h"), _tk(key_id="b", key_hash="h")])
        assert manager._key_rotator.ensure_key_ids(config) is False
        assert called["n"] == 0  # no id generated when every entry has one


class TestFindKeyIndex:
    def test_returns_matching_index(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        config = ApiKeysConfig(keys=[_tk(key_id="a", key_hash="h"), _tk(key_id="b", key_hash="h")])
        assert manager._key_rotator.find_key_index(config, "b") == 1

    def test_returns_none_when_absent(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        config = ApiKeysConfig(keys=[_tk(key_id="a", key_hash="h")])
        assert manager._key_rotator.find_key_index(config, "missing") is None


# --------------------------------------------------------------------------- #
# cleanup-timer scheduling / cancellation  (Timer is the record-only fake)
# --------------------------------------------------------------------------- #


class TestScheduleRotationCleanup:
    def test_noop_without_key_id(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(
            key_id=None,
            key_hash="h",
            previous_key_active_until=datetime.now(UTC) + timedelta(seconds=300),
        )
        manager._key_rotator.schedule_rotation_cleanup(item)
        assert manager._rotation_cleanup_timers == {}

    def test_noop_without_active_until(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(key_id="k-1", key_hash="h", previous_key_active_until=None)
        manager._key_rotator.schedule_rotation_cleanup(item)
        assert manager._rotation_cleanup_timers == {}

    def test_noop_when_already_expired(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(
            key_id="k-1",
            key_hash="h",
            previous_key_active_until=datetime.now(UTC) - timedelta(seconds=1),
        )
        manager._key_rotator.schedule_rotation_cleanup(item)
        assert manager._rotation_cleanup_timers == {}

    def test_schedules_timer_wired_to_expire_with_key_id_arg(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(
            key_id="k-1",
            key_hash="h",
            previous_key_active_until=datetime.now(UTC) + timedelta(seconds=300),
        )
        manager._key_rotator.schedule_rotation_cleanup(item)
        timer = manager._rotation_cleanup_timers["k-1"]
        assert isinstance(timer, _FakeTimer)
        assert timer.started is True
        assert timer.daemon is True
        assert 0 < timer.delay <= 300
        # callback + args wiring pinned (kills function=None / args=None / dropped).
        assert timer.function == manager._key_rotator.expire_previous_key
        assert timer.args == ("k-1",)

    def test_reschedule_cancels_only_the_same_keys_prior_timer(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # schedule_rotation_cleanup cancels the existing timer for THIS key BEFORE
        # scheduling the new one -- cancel(item.key_id), not cancel(None). A
        # cancel(None) mutant would fall through to the cancel-ALL branch and also
        # kill an unrelated sibling timer, so the sibling must survive untouched.
        old = _FakeTimer(300, None)
        sibling = _FakeTimer(300, None)
        manager._rotation_cleanup_timers["k-1"] = old
        manager._rotation_cleanup_timers["k-2"] = sibling
        item = _tk(
            key_id="k-1",
            key_hash="h",
            previous_key_active_until=datetime.now(UTC) + timedelta(seconds=300),
        )
        manager._key_rotator.schedule_rotation_cleanup(item)
        assert old.cancelled is True
        assert manager._rotation_cleanup_timers["k-1"] is not old
        assert sibling.cancelled is False  # cancel(key_id), not cancel-all
        assert manager._rotation_cleanup_timers["k-2"] is sibling


class TestCancelRotationCleanupTimers:
    def test_cancels_single_named_timer(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        t1, t2 = _FakeTimer(1, None), _FakeTimer(1, None)
        manager._rotation_cleanup_timers = {"a": t1, "b": t2}
        manager._key_rotator.cancel_rotation_cleanup_timers("a")
        assert t1.cancelled is True
        assert "a" not in manager._rotation_cleanup_timers
        assert "b" in manager._rotation_cleanup_timers  # untouched
        assert t2.cancelled is False

    def test_unknown_named_timer_is_noop(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        manager._rotation_cleanup_timers = {}
        manager._key_rotator.cancel_rotation_cleanup_timers("missing")  # pop(None) must not raise

    def test_cancels_all_when_no_id(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        t1, t2 = _FakeTimer(1, None), _FakeTimer(1, None)
        manager._rotation_cleanup_timers = {"a": t1, "b": t2}
        manager._key_rotator.cancel_rotation_cleanup_timers()
        assert t1.cancelled is True
        assert t2.cancelled is True
        assert manager._rotation_cleanup_timers == {}


# --------------------------------------------------------------------------- #
# expire_previous_key
# --------------------------------------------------------------------------- #


class TestExpirePreviousKey:
    def test_unknown_id_is_silently_swallowed(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # revoke_old_key raises KeyError for an unknown id; expire swallows it.
        manager._key_rotator.expire_previous_key("does-not-exist")

    def test_revokes_old_after_rotation(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator
        monkeypatch.setattr(
            rotator, "generate_key", lambda tenant, name: "af-prod-acme-rotation-agent-" + "y" * 43
        )
        monkeypatch.setattr(kr, "hash_api_key", _rec_hash([]))
        monkeypatch.setattr(kr, "compute_key_lookup", _rec_lookup())
        manager.rotate_key(SEED_KEY_ID)

        rotator.expire_previous_key(SEED_KEY_ID)
        assert rotator.rotation_phase(manager._keys_by_id[SEED_KEY_ID]) == "idle"

    def test_unexpected_error_is_logged_not_raised(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        rotator = manager._key_rotator

        def _boom(_key_id: str) -> bool:
            raise RuntimeError("disk gone")

        monkeypatch.setattr(rotator, "revoke_old_key", _boom)
        import src.serving.api.auth as auth_pkg

        warnings: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            auth_pkg.logger, "warning", lambda event, **kw: warnings.append((event, kw))
        )
        # A non-KeyError must be caught and logged, never propagated.
        rotator.expire_previous_key("k-1")
        assert warnings
        event, kwargs = warnings[0]
        assert event == "api_key_rotation_cleanup_failed"
        assert kwargs["key_id"] == "k-1"
        assert "disk gone" in kwargs["error"]


# --------------------------------------------------------------------------- #
# validate_generated_key
# --------------------------------------------------------------------------- #


class TestValidateGeneratedKey:
    def test_none_does_not_raise(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        manager._key_rotator.validate_generated_key(None)

    def test_short_key_raises(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        manager.security_policy.min_key_length = 20
        with pytest.raises(ValueError, match="below min_key_length"):
            manager._key_rotator.validate_generated_key("x" * 19)

    def test_exactly_min_length_is_allowed(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        # len < min raises; len == min must pass (pins the strict `<`).
        manager.security_policy.min_key_length = 20
        manager._key_rotator.validate_generated_key("x" * 20)


# --------------------------------------------------------------------------- #
# _storage_payload
# --------------------------------------------------------------------------- #


class TestStoragePayload:
    def test_hashed_entry_drops_plaintext_and_json_serialises_dates(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(key="plain", key_hash="the-hash")
        payload = manager._key_rotator._storage_payload(item)
        assert payload["key_hash"] == "the-hash"
        assert "key" not in payload  # plaintext stripped when a hash is present
        # mode="json" -> the date is serialised to an ISO string, not a date
        # object (kills mode=None / dropped-mode / re-cased-mode mutants).
        assert payload["created_at"] == "2026-01-01"
        assert isinstance(payload["created_at"], str)

    def test_plaintext_only_entry_keeps_key(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        item = _tk(key="plain", key_hash=None)
        payload = manager._key_rotator._storage_payload(item)
        assert payload["key"] == "plain"
        assert "key_hash" not in payload  # exclude_none drops the absent hash


# --------------------------------------------------------------------------- #
# write_config
# --------------------------------------------------------------------------- #


class TestWriteConfig:
    def test_without_path_raises(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        manager.api_keys_path = None
        # Anchored so an XX-wrapped / re-cased message mutant is killed.
        with pytest.raises(
            RuntimeError,
            match=r"^AGENTFLOW_API_KEYS_FILE must be configured for key management\.$",
        ):
            manager._key_rotator.write_config(ApiKeysConfig(keys=[]))

    def test_writes_block_yaml_in_field_order_without_plaintext(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        import yaml

        config = ApiKeysConfig(keys=[_tk(key="plain", key_hash="h", key_id="id-1")])
        manager._key_rotator.write_config(config)
        text = manager.api_keys_path.read_text(encoding="utf-8")
        # Block-style YAML, not JSON (kills the `yaml is not None` flip that would
        # fall through to json.dumps -- which safe_load would still parse).
        assert not text.lstrip().startswith("{")
        # sort_keys=False -> insertion (model field) order, so key_id precedes the
        # alphabetically-earlier created_at (kills sort_keys=True/None/dropped).
        assert text.index("key_id") < text.index("created_at")
        data = yaml.safe_load(text)
        [entry] = data["keys"]
        assert entry["key_id"] == "id-1"
        assert entry["key_hash"] == "h"
        assert "key" not in entry

    def test_creates_missing_parent_directories(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # parents=True must create the full chain; a parents=False/dropped mutant
        # raises FileNotFoundError on the missing intermediate dir.
        manager = _build_manager(tmp_path, monkeypatch)
        deep = tmp_path / "newa" / "newb" / "api_keys.yaml"  # type: ignore[operator]
        manager.api_keys_path = deep
        manager._key_rotator.write_config(ApiKeysConfig(keys=[_tk(key="p", key_id="id-1")]))
        assert deep.exists()


# --------------------------------------------------------------------------- #
# rotate_all_keys (module-level)
# --------------------------------------------------------------------------- #


class TestRotateAllKeys:
    def test_rotates_every_keyed_entry_and_skips_idless(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = _build_manager(tmp_path, monkeypatch)
        monkeypatch.setattr(
            manager,
            "list_keys_with_usage",
            lambda: [{"key_id": "a"}, {"key_id": None}, {"key_id": "b"}],
        )
        rotated_ids: list[str] = []

        def _rotate(key_id: str) -> tuple[TenantKey, datetime]:
            rotated_ids.append(key_id)
            return _tk(key_hash="h"), datetime.now(UTC)

        monkeypatch.setattr(manager, "rotate_key", _rotate)

        rotated = rotate_all_keys(manager)
        assert rotated_ids == ["a", "b"]  # None key_id skipped
        assert len(rotated) == 2
