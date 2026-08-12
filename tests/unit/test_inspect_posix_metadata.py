"""Focused unit tests for the C05 node-scoped POSIX metadata inspector.

Deterministic on Windows: all filesystem and privilege surfaces are faked.
No real root, POSIX xattrs, Docker, network, or live node access.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "inspect_posix_metadata.py"

SCHEMA_VERSION = "c05-posix-metadata-v1"
PASS_STATUS = "METADATA_INSPECTION_PASS"  # noqa: S105 — status token, not a secret
BLOCKED_STATUS = "METADATA_INSPECTION_BLOCKED"
ACL_ACCESS = "system.posix_acl_access"
ACL_DEFAULT = "system.posix_acl_default"

REQUIRED_ENTRY_FIELDS = (
    "relative_path",
    "object_type",
    "apparent_size",
    "allocated_blocks",
    "mtime_ns",
    "ctime_ns",
    "inode",
    "device",
    "uid",
    "gid",
    "mode",
    "symlink_target",
    "hard_link_group",
    "xattr_count",
    "posix_acl_access_present",
    "posix_acl_default_present",
    "xattr_digest",
)


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing inspector at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "inspect_posix_metadata_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeStat:
    st_mode: int
    st_ino: int
    st_dev: int
    st_nlink: int = 1
    st_uid: int = 0
    st_gid: int = 0
    st_size: int = 0
    st_blocks: int = 0
    st_mtime_ns: int = 1_000_000_000
    st_ctime_ns: int = 2_000_000_000


@dataclass
class FakeNode:
    mode: int
    inode: int
    device: int = 100
    nlink: int = 1
    uid: int = 0
    gid: int = 0
    size: int = 0
    blocks: int = 0
    mtime_ns: int = 1_000_000_000
    ctime_ns: int = 2_000_000_000
    children: dict[str, FakeNode] = field(default_factory=dict)
    symlink_target: str | None = None
    xattrs: dict[str, bytes] = field(default_factory=dict)
    # Mutation hooks for drift tests
    lstat_calls: int = 0
    mutate_after_lstat: Callable[[FakeNode], None] | None = None
    mutate_after_xattr_list: Callable[[FakeNode], None] | None = None
    disappear_after: int | None = None


def _is_dir(mode: int) -> bool:
    return stat.S_ISDIR(mode)


def _is_reg(mode: int) -> bool:
    return stat.S_ISREG(mode)


def _is_lnk(mode: int) -> bool:
    return stat.S_ISLNK(mode)


class FakeFs:
    """In-memory lstat/listdir/xattr surface with follow_symlinks=False only."""

    def __init__(self, root_path: str, root: FakeNode) -> None:
        self.root_path = root_path.rstrip("/") or root_path
        self.root = root
        self.open_calls: list[Any] = []
        self.listxattr_available = True
        self.getxattr_available = True
        self.listxattr_error: OSError | None = None
        self.getxattr_error: OSError | None = None

    def _lookup(self, path: str) -> FakeNode:
        norm = path.rstrip("/") or path
        if norm == self.root_path:
            return self.root
        if not norm.startswith(self.root_path + "/") and norm != self.root_path:
            raise FileNotFoundError(path)
        rel = norm[len(self.root_path) + 1 :]
        parts = [p for p in rel.split("/") if p]
        node = self.root
        for part in parts:
            if not _is_dir(node.mode):
                raise NotADirectoryError(path)
            # Never traverse symlink directories: caller must not request that.
            if part not in node.children:
                raise FileNotFoundError(path)
            node = node.children[part]
        return node

    def _snapshot(self, node: FakeNode) -> FakeStat:
        return FakeStat(
            st_mode=node.mode,
            st_ino=node.inode,
            st_dev=node.device,
            st_nlink=node.nlink,
            st_uid=node.uid,
            st_gid=node.gid,
            st_size=node.size,
            st_blocks=node.blocks,
            st_mtime_ns=node.mtime_ns,
            st_ctime_ns=node.ctime_ns,
        )

    def lstat(self, path: str) -> FakeStat:
        node = self._lookup(path)
        node.lstat_calls += 1
        if node.disappear_after is not None and node.lstat_calls > node.disappear_after:
            raise FileNotFoundError(path)
        # Apply any mutation scheduled by the previous lstat before this read.
        pending = getattr(node, "_pending_mutation", None)
        if pending is not None:
            node._pending_mutation = None  # type: ignore[attr-defined]
            pending()
        result = self._snapshot(node)
        if node.mutate_after_lstat is not None:
            mutator = node.mutate_after_lstat
            node.mutate_after_lstat = None

            def _apply(n: FakeNode = node, fn: Callable[[FakeNode], None] = mutator) -> None:
                fn(n)

            node._pending_mutation = _apply  # type: ignore[attr-defined]
        return result

    def listdir(self, path: str) -> list[str]:
        node = self._lookup(path)
        if not _is_dir(node.mode):
            raise NotADirectoryError(path)
        return list(node.children.keys())

    def readlink(self, path: str) -> str:
        node = self._lookup(path)
        if not _is_lnk(node.mode):
            raise OSError("not a symlink")
        assert node.symlink_target is not None
        return node.symlink_target

    def listxattr(self, path: str, *, follow_symlinks: bool = True) -> list[str]:
        if follow_symlinks:
            raise AssertionError("listxattr must use follow_symlinks=False")
        if not self.listxattr_available:
            raise AttributeError("listxattr")
        if self.listxattr_error is not None:
            raise self.listxattr_error
        node = self._lookup(path)
        names = list(node.xattrs.keys())
        if node.mutate_after_xattr_list is not None:
            node.mutate_after_xattr_list(node)
            node.mutate_after_xattr_list = None
        return names

    def getxattr(self, path: str, attribute: str, *, follow_symlinks: bool = True) -> bytes:
        if follow_symlinks:
            raise AssertionError("getxattr must use follow_symlinks=False")
        if not self.getxattr_available:
            raise AttributeError("getxattr")
        if self.getxattr_error is not None:
            raise self.getxattr_error
        node = self._lookup(path)
        if attribute not in node.xattrs:
            raise OSError(f"xattr missing: {attribute}")
        return node.xattrs[attribute]

    def guarded_open(self, *args: Any, **kwargs: Any) -> Any:
        self.open_calls.append((args, kwargs))
        raise AssertionError("regular-file contents must never be opened")


def _dir(inode: int, **kwargs: Any) -> FakeNode:
    return FakeNode(mode=stat.S_IFDIR | 0o755, inode=inode, **kwargs)


def _file(inode: int, size: int = 4, blocks: int = 8, **kwargs: Any) -> FakeNode:
    return FakeNode(
        mode=stat.S_IFREG | 0o644,
        inode=inode,
        size=size,
        blocks=blocks,
        **kwargs,
    )


def _link(inode: int, target: str, **kwargs: Any) -> FakeNode:
    return FakeNode(
        mode=stat.S_IFLNK | 0o777,
        inode=inode,
        size=len(target),
        blocks=0,
        symlink_target=target,
        **kwargs,
    )


def _expected_digest(xattrs: dict[str, bytes]) -> str:
    pairs = sorted(
        ((name.encode("utf-8"), value) for name, value in xattrs.items()),
        key=lambda item: item[0],
    )
    hasher = hashlib.sha256()
    for name_b, value in pairs:
        hasher.update(struct.pack(">Q", len(name_b)))
        hasher.update(name_b)
        hasher.update(struct.pack(">Q", len(value)))
        hasher.update(value)
    return hasher.hexdigest()


def _install_fs(module: Any, monkeypatch: pytest.MonkeyPatch, fs: FakeFs, *, euid: int = 0) -> None:
    monkeypatch.setattr(module.os, "geteuid", lambda: euid, raising=False)
    monkeypatch.setattr(module, "geteuid", lambda: euid, raising=False)
    monkeypatch.setattr(module.os, "lstat", fs.lstat)
    monkeypatch.setattr(module.os, "listdir", fs.listdir)
    monkeypatch.setattr(module.os, "readlink", fs.readlink)
    if fs.listxattr_available:
        monkeypatch.setattr(module.os, "listxattr", fs.listxattr, raising=False)
    else:
        if hasattr(module.os, "listxattr"):
            monkeypatch.delattr(module.os, "listxattr", raising=False)
    if fs.getxattr_available:
        monkeypatch.setattr(module.os, "getxattr", fs.getxattr, raising=False)
    else:
        if hasattr(module.os, "getxattr"):
            monkeypatch.delattr(module.os, "getxattr", raising=False)
    monkeypatch.setattr(module, "open", fs.guarded_open, raising=False)
    monkeypatch.setattr("builtins.open", fs.guarded_open)


def _sample_tree() -> tuple[str, FakeNode]:
    root_path = "/node/data"
    # Children intentionally inserted out of bytewise order.
    root = _dir(
        1,
        children={
            "z-file": _file(10, size=10, blocks=16, xattrs={"user.z": b"zz", "user.a": b"aa"}),
            "a-dir": _dir(
                2,
                children={
                    "b-file": _file(3, size=3, blocks=8, nlink=2),
                    "c-link": _link(4, "b-file"),
                },
            ),
            "m-link": _link(5, "../outside"),
        },
    )
    # Hard-link twin sharing device/inode with b-file
    root.children["a-dir"].children["b-twin"] = _file(
        3,
        size=3,
        blocks=8,
        nlink=2,
    )
    return root_path, root


def test_module_importable_on_first_red() -> None:
    """First-file existence/import gate; remaining tests cover behavior."""
    assert SCRIPT_PATH.exists()
    module = _load_module()
    assert hasattr(module, "inspect_posix_metadata")
    assert hasattr(module, "main")


def test_deterministic_traversal_order_and_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path, root = _sample_tree()
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)

    result = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=20,
    )

    assert result["status"] == PASS_STATUS
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["effective_uid"] == 0
    assert result["root"]["path"] == root_path
    assert result["root"]["device"] == 100
    assert result["root"]["inode"] == 1

    paths = [entry["relative_path"] for entry in result["entries"]]
    assert paths == [
        ".",
        "a-dir",
        "a-dir/b-file",
        "a-dir/b-twin",
        "a-dir/c-link",
        "m-link",
        "z-file",
    ]
    assert result["entry_count"] == len(paths)

    for entry in result["entries"]:
        for field_name in REQUIRED_ENTRY_FIELDS:
            assert field_name in entry, field_name

    by_path = {entry["relative_path"]: entry for entry in result["entries"]}
    assert by_path["."]["object_type"] == "directory"
    assert by_path["z-file"]["object_type"] == "regular_file"
    assert by_path["z-file"]["apparent_size"] == 10
    assert by_path["z-file"]["allocated_blocks"] == 16
    assert by_path["a-dir/c-link"]["object_type"] == "symlink"
    assert by_path["a-dir/c-link"]["symlink_target"] == "b-file"
    assert by_path["z-file"]["symlink_target"] is None
    assert by_path["a-dir/b-file"]["hard_link_group"] == "100:3"
    assert by_path["a-dir/b-twin"]["hard_link_group"] == "100:3"
    assert by_path["z-file"]["hard_link_group"] is None
    assert by_path["z-file"]["mtime_ns"] == 1_000_000_000
    assert by_path["z-file"]["ctime_ns"] == 2_000_000_000
    assert by_path["z-file"]["uid"] == 0
    assert by_path["z-file"]["gid"] == 0
    assert isinstance(by_path["z-file"]["mode"], int)
    claim = result["claim_boundary"]
    assert claim["metadata_only"] is True
    assert claim["file_contents_read"] is False
    assert claim["c05_approved"] is False
    assert claim["branch_approved"] is False
    assert claim["capture_approved"] is False
    assert claim["production_approved"] is False


def test_xattr_digest_order_independent_length_prefixed_and_non_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/xattr"
    xattrs_a = {"user.beta": b"B", "user.alpha": b"A"}
    xattrs_b = {"user.alpha": b"A", "user.beta": b"B"}
    root_a = _dir(1, xattrs=xattrs_a)
    root_b = _dir(1, xattrs=xattrs_b)

    fs_a = FakeFs(root_path, root_a)
    _install_fs(module, monkeypatch, fs_a)
    result_a = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=5,
    )

    fs_b = FakeFs(root_path, root_b)
    _install_fs(module, monkeypatch, fs_b)
    result_b = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=5,
    )

    digest = result_a["entries"][0]["xattr_digest"]
    assert digest == result_b["entries"][0]["xattr_digest"]
    assert digest == _expected_digest(xattrs_a)
    assert result_a["entries"][0]["xattr_count"] == 2

    # Ambiguity resistance: length-prefix must distinguish concatenated shapes.
    amb_a = {"user.ab": b"c"}
    amb_b = {"user.a": b"bc"}
    assert _expected_digest(amb_a) != _expected_digest(amb_b)
    root_amb = _dir(1, xattrs=amb_a)
    fs_amb = FakeFs(root_path, root_amb)
    _install_fs(module, monkeypatch, fs_amb)
    result_amb = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=5,
    )
    assert result_amb["entries"][0]["xattr_digest"] == _expected_digest(amb_a)
    assert result_amb["entries"][0]["xattr_digest"] != _expected_digest(amb_b)

    dumped = json.dumps(result_a)
    assert "user.alpha" not in dumped
    assert "user.beta" not in dumped
    # Explicit non-leak: raw xattr values must not appear as JSON string values.
    # Digest hex may contain letters a-f; quote-bounded checks exclude that case.
    assert '"A"' not in dumped
    assert '"B"' not in dumped
    # Values must not appear as any emitted string field content.
    for entry in result_a["entries"]:
        for value in entry.values():
            if isinstance(value, str):
                assert value not in {"A", "B"}
    # ensure_ascii JSON must not embed the value via unicode escapes either.
    assert "\\u0041" not in dumped  # 'A'
    assert "\\u0042" not in dumped  # 'B'


def test_acl_presence_flags_and_digest_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/acl"
    xattrs = {
        ACL_ACCESS: b"\x02\x00",
        ACL_DEFAULT: b"\x03\x00",
        "user.keep": b"secret-value-must-not-leak",
    }
    root = _dir(7, xattrs=xattrs)
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)

    result = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=7,
        max_entries=3,
    )
    entry = result["entries"][0]
    assert entry["posix_acl_access_present"] is True
    assert entry["posix_acl_default_present"] is True
    assert entry["xattr_count"] == 3
    assert entry["xattr_digest"] == _expected_digest(xattrs)
    dumped = json.dumps(result)
    assert ACL_ACCESS not in dumped
    assert ACL_DEFAULT not in dumped
    assert "secret-value-must-not-leak" not in dumped


def test_root_path_type_uid_device_inode_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/root"
    root = _dir(9)
    fs = FakeFs(root_path, root)

    # Non-root euid
    _install_fs(module, monkeypatch, fs, euid=1000)
    with pytest.raises(module.MetadataInspectionBlocked, match="uid|euid|privilege|root"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=9,
            max_entries=5,
        )

    # Relative path
    _install_fs(module, monkeypatch, fs, euid=0)
    with pytest.raises(module.MetadataInspectionBlocked, match="absolute"):
        module.inspect_posix_metadata(
            root="relative/path",
            expected_device=100,
            expected_inode=9,
            max_entries=5,
        )

    # Device mismatch
    with pytest.raises(module.MetadataInspectionBlocked, match="device"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=999,
            expected_inode=9,
            max_entries=5,
        )

    # Inode mismatch
    with pytest.raises(module.MetadataInspectionBlocked, match="inode"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=5,
        )

    # Root is symlink
    link_root = _link(9, "/somewhere")
    fs_link = FakeFs(root_path, link_root)
    _install_fs(module, monkeypatch, fs_link, euid=0)
    with pytest.raises(module.MetadataInspectionBlocked, match="symlink|directory"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=9,
            max_entries=5,
        )


def test_symlink_not_traversed_special_and_cross_device_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/walk"

    # Symlink must be inventoried as a symlink leaf; never listdir/traverse into it.
    root = _dir(
        1,
        children={
            "link-as-dir": _link(2, "trap-target"),
            "real-file": _file(3),
        },
    )
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)
    result = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=10,
    )
    paths = [e["relative_path"] for e in result["entries"]]
    assert paths == [".", "link-as-dir", "real-file"]
    assert "link-as-dir/secret" not in paths
    assert "trap-target" not in paths
    assert "trap-target/secret" not in paths
    assert result["entries"][paths.index("link-as-dir")]["object_type"] == "symlink"
    assert result["entries"][paths.index("link-as-dir")]["symlink_target"] == "trap-target"

    # FIFO rejection
    fifo_root = _dir(1, children={"pipe": FakeNode(mode=stat.S_IFIFO | 0o644, inode=3)})
    fs_fifo = FakeFs(root_path, fifo_root)
    _install_fs(module, monkeypatch, fs_fifo)
    with pytest.raises(module.MetadataInspectionBlocked, match="type|fifo|special|unsupported"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=10,
        )

    # Cross-device rejection
    xd_root = _dir(1, children={"other": _file(2, device=200)})
    fs_xd = FakeFs(root_path, xd_root)
    _install_fs(module, monkeypatch, fs_xd)
    with pytest.raises(module.MetadataInspectionBlocked, match="device"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=10,
        )


def test_max_entries_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/max"
    root = _dir(
        1,
        children={
            "a": _file(2),
            "b": _file(3),
            "c": _file(4),
        },
    )
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)
    with pytest.raises(module.MetadataInspectionBlocked, match="max_entries|too many|overflow"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=3,  # root + 3 children would be 4
        )


def test_xattr_api_absence_error_and_name_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/xfail"

    fs_missing = FakeFs(root_path, _dir(1))
    fs_missing.listxattr_available = False
    _install_fs(module, monkeypatch, fs_missing)
    with pytest.raises(module.MetadataInspectionBlocked, match="listxattr|xattr"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=5,
        )

    # Missing getxattr must fail closed even when listxattr is present.
    fs_no_get = FakeFs(root_path, _dir(1, xattrs={"user.a": b"1"}))
    fs_no_get.getxattr_available = False
    _install_fs(module, monkeypatch, fs_no_get)
    with pytest.raises(module.MetadataInspectionBlocked, match="getxattr|xattr"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=5,
        )

    fs_err = FakeFs(root_path, _dir(1, xattrs={"user.a": b"1"}))
    fs_err.listxattr_error = OSError("xattr list denied")
    _install_fs(module, monkeypatch, fs_err)
    with pytest.raises(module.MetadataInspectionBlocked, match="xattr|OSError|list"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=5,
        )

    drift_root = _dir(1, xattrs={"user.a": b"1", "user.b": b"2"})

    def drop_b(node: FakeNode) -> None:
        node.xattrs.pop("user.b", None)

    drift_root.mutate_after_xattr_list = drop_b
    fs_drift = FakeFs(root_path, drift_root)
    _install_fs(module, monkeypatch, fs_drift)
    with pytest.raises(module.MetadataInspectionBlocked, match="drift|xattr"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=5,
        )


def test_per_entry_and_root_stat_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/drift"

    # Per-entry size mutation between before/after lstat.
    child = _file(2, size=10)

    def grow(node: FakeNode) -> None:
        node.size = 99

    child.mutate_after_lstat = grow
    root = _dir(1, children={"f": child})
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)
    with pytest.raises(module.MetadataInspectionBlocked, match="drift|stat|mutat"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=10,
        )

    # Whole-root drift after traversal: keep root stable through entry
    # inspection (validation + before/after = 3 lstats), mutate on the
    # post-traversal identity check (4th root lstat).
    stable_child = _file(2, size=1)
    root2 = _dir(1, children={"f": stable_child})
    call_state = {"n": 0}
    fs2 = FakeFs(root_path, root2)

    def lstat_with_root_drift(path: str) -> FakeStat:
        st = fs2.lstat(path)
        if path.rstrip("/") == root_path:
            call_state["n"] += 1
            if call_state["n"] >= 4:
                return FakeStat(
                    st_mode=st.st_mode,
                    st_ino=st.st_ino,
                    st_dev=st.st_dev,
                    st_nlink=st.st_nlink,
                    st_uid=st.st_uid,
                    st_gid=st.st_gid,
                    st_size=st.st_size,
                    st_blocks=st.st_blocks,
                    st_mtime_ns=st.st_mtime_ns + 1,
                    st_ctime_ns=st.st_ctime_ns,
                )
        return st

    _install_fs(module, monkeypatch, fs2)
    monkeypatch.setattr(module.os, "lstat", lstat_with_root_drift)
    with pytest.raises(module.MetadataInspectionBlocked, match="root stat drift|drift"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=10,
        )


def test_cli_success_and_blocked_json_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    root_path = "/node/cli"
    root = _dir(1, children={"a": _file(2)})
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)

    code = module.main(
        [
            "--root",
            root_path,
            "--expected-device",
            "100",
            "--expected-inode",
            "1",
            "--max-entries",
            "10",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == PASS_STATUS
    assert payload["entry_count"] == 2
    assert "entries" in payload
    assert payload["entries"]

    # Blocked path: wrong inode
    code = module.main(
        [
            "--root",
            root_path,
            "--expected-device",
            "100",
            "--expected-inode",
            "999",
            "--max-entries",
            "10",
        ]
    )
    assert code != 0
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == BLOCKED_STATUS
    assert blocked.get("entries") in ([], None)
    assert blocked.get("entry_count", 0) == 0
    assert "reason" in blocked
    assert blocked["reason"]
    assert "user." not in json.dumps(blocked)


def test_regular_file_contents_never_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    root_path = "/node/noread"
    root = _dir(
        1,
        children={
            "blob": _file(2, size=1024, blocks=8, xattrs={"user.t": b"v"}),
        },
    )
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)

    result = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=10,
    )
    assert result["status"] == PASS_STATUS
    assert fs.open_calls == []
    # Ensure module surface itself does not expose a content reader.
    assert not hasattr(module, "read_file_contents")


def test_cli_parse_failures_emit_blocked_json_not_argparse_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing/invalid CLI flags must emit one bounded blocked JSON object."""
    module = _load_module()

    # Missing required flags: argparse usage must not replace strict JSON.
    code = module.main(["--root", "/node"])
    assert code != 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == BLOCKED_STATUS
    assert payload.get("entries") == []
    assert payload.get("entry_count", 0) == 0
    assert "reason" in payload
    assert payload["reason"]
    assert "usage:" not in captured.out.lower()
    # Bounded non-secret reason: do not echo path tokens from partial argv as data.
    dumped = json.dumps(payload)
    assert "user." not in dumped

    # Invalid integer input must fail closed without echoing the raw token.
    code = module.main(
        [
            "--root",
            "/node",
            "--expected-device",
            "not-an-int",
            "--expected-inode",
            "1",
            "--max-entries",
            "10",
        ]
    )
    assert code != 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == BLOCKED_STATUS
    assert payload.get("entries") == []
    assert payload.get("entry_count", 0) == 0
    assert "not-an-int" not in captured.out
    assert "not-an-int" not in captured.err
    assert "usage:" not in captured.out.lower()

    # Normal --help remains exit 0 with help text (not blocked JSON).
    with pytest.raises(SystemExit) as help_exc:
        module.main(["--help"])
    assert help_exc.value.code in (0, None)
    help_captured = capsys.readouterr()
    help_text = help_captured.out + help_captured.err
    assert "usage:" in help_text.lower() or "--root" in help_text
    with pytest.raises(json.JSONDecodeError):
        json.loads(help_captured.out)


def test_posix_absolute_roots_and_literal_backslash_filenames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux Kind-node paths: POSIX absolute only; preserve literal backslashes."""
    module = _load_module()

    # Windows drive / UNC spellings must be rejected even if OS path rules differ.
    for bad_root in ("C:/node", "C:\\node", "\\\\server\\share", "//server/share"):
        with pytest.raises(module.MetadataInspectionBlocked, match="absolute"):
            module.inspect_posix_metadata(
                root=bad_root,
                expected_device=100,
                expected_inode=1,
                max_entries=5,
            )

    # Deterministic tree: literal filename a\b is distinct from nested a/b.
    root_path = "/node/bs"
    literal_name = "a\\b"
    root = _dir(
        1,
        children={
            literal_name: _file(2, size=11, blocks=8),
            "a": _dir(
                3,
                children={
                    "b": _file(4, size=22, blocks=16),
                },
            ),
        },
    )
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)
    result = module.inspect_posix_metadata(
        root=root_path,
        expected_device=100,
        expected_inode=1,
        max_entries=10,
    )
    assert result["status"] == PASS_STATUS
    paths = [entry["relative_path"] for entry in result["entries"]]
    assert paths == [".", "a", "a/b", literal_name]
    by_path = {entry["relative_path"]: entry for entry in result["entries"]}
    assert by_path[literal_name]["inode"] == 2
    assert by_path[literal_name]["apparent_size"] == 11
    assert by_path["a/b"]["inode"] == 4
    assert by_path["a/b"]["apparent_size"] == 22
    assert by_path[literal_name]["relative_path"] != by_path["a/b"]["relative_path"]


def test_nested_directory_drift_during_traversal_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested dir identity must be re-checked after its subtree is walked."""
    module = _load_module()
    root_path = "/node/nested-drift"

    nested = _dir(2, mtime_ns=5_000_000_000)
    child = _file(3, size=1)

    def bump_nested_identity(_node: FakeNode) -> None:
        # Simulate descendant create/delete changing the parent directory.
        nested.mtime_ns = 9_000_000_000
        nested.ctime_ns = 9_100_000_000

    child.mutate_after_lstat = bump_nested_identity
    nested.children["child"] = child
    root = _dir(1, children={"nested": nested})
    fs = FakeFs(root_path, root)
    _install_fs(module, monkeypatch, fs)

    with pytest.raises(module.MetadataInspectionBlocked, match="drift|disappear|stat"):
        module.inspect_posix_metadata(
            root=root_path,
            expected_device=100,
            expected_inode=1,
            max_entries=10,
        )
