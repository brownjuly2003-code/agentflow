#!/usr/bin/env python3
"""C05 node-scoped non-secret POSIX metadata inventory (local reader only).

Fail-closed metadata inspector intended for later separately authorized
execution inside a Linux Kind node. Standard library only. Never opens regular
file contents, never invokes SSH/Docker/kubectl/tar/subprocess/DB libraries.

This module is not evidence of a live node run and does not approve C05,
branch, capture, or production status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import struct
import sys
from collections.abc import Sequence
from typing import Any

SCHEMA_VERSION = "c05-posix-metadata-v1"
PASS_STATUS = "METADATA_INSPECTION_PASS"  # noqa: S105 — status token, not a secret
BLOCKED_STATUS = "METADATA_INSPECTION_BLOCKED"

POSIX_ACL_ACCESS = "system.posix_acl_access"
POSIX_ACL_DEFAULT = "system.posix_acl_default"

CLAIM_BOUNDARY: dict[str, Any] = {
    "metadata_only": True,
    "file_contents_read": False,
    "c05_approved": False,
    "branch_approved": False,
    "capture_approved": False,
    "production_approved": False,
    "claim_scope": (
        "Metadata-only inventory. No regular-file contents were read. "
        "Does not approve C05, branch eligibility, capture, or production."
    ),
}


class MetadataInspectionBlocked(Exception):  # noqa: N818 — domain blocked outcome, not a programmer Error
    """Expected fail-closed validation or inspection failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def geteuid() -> int:
    """Return effective UID; fail closed when the platform has no geteuid."""
    fn = getattr(os, "geteuid", None)
    if fn is None:
        raise MetadataInspectionBlocked("effective UID API unavailable (os.geteuid missing)")
    return int(fn())


def _require_positive_int(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MetadataInspectionBlocked(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MetadataInspectionBlocked(f"{name} must be a non-negative integer")
    return value


def _is_absolute_path(path: str) -> bool:
    """Return True only for POSIX absolute paths (Linux Kind-node contract).

    Rejects Windows drive letters and UNC spellings even when the local OS
    would treat them as absolute.
    """
    if not isinstance(path, str) or not path:
        return False
    # UNC: //server/share or \\server\share
    if path.startswith("//") or path.startswith("\\\\"):
        return False
    # Windows drive: C:... or C\...
    if len(path) >= 2 and path[0].isalpha() and path[1] == ":":
        return False
    return path.startswith("/")


def _stat_identity(st: os.stat_result) -> tuple[Any, ...]:
    blocks = getattr(st, "st_blocks", None)
    if blocks is None:
        raise MetadataInspectionBlocked("st_blocks absent; allocated block count required")
    return (
        int(st.st_dev),
        int(st.st_ino),
        int(st.st_mode),
        int(st.st_nlink),
        int(st.st_uid),
        int(st.st_gid),
        int(st.st_size),
        int(blocks),
        int(st.st_mtime_ns),
        int(st.st_ctime_ns),
    )


def _object_type(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular_file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        raise MetadataInspectionBlocked("unsupported special object type: fifo")
    if stat.S_ISSOCK(mode):
        raise MetadataInspectionBlocked("unsupported special object type: socket")
    if stat.S_ISCHR(mode):
        raise MetadataInspectionBlocked("unsupported special object type: character device")
    if stat.S_ISBLK(mode):
        raise MetadataInspectionBlocked("unsupported special object type: block device")
    raise MetadataInspectionBlocked("unsupported or unknown object type")


def _encode_xattr_name(name: str | bytes) -> bytes:
    if isinstance(name, bytes):
        return name
    return os.fsencode(name)


def _name_as_str(name: str | bytes) -> str:
    if isinstance(name, str):
        return name
    return os.fsdecode(name)


def digest_xattr_pairs(pairs: Sequence[tuple[bytes, bytes]]) -> str:
    """SHA-256 over length-prefixed name/value pairs sorted by name bytes."""
    hasher = hashlib.sha256()
    for name_b, value in sorted(pairs, key=lambda item: item[0]):
        if not isinstance(value, (bytes, bytearray)):
            raise MetadataInspectionBlocked("xattr value must be bytes")
        value_b = bytes(value)
        hasher.update(struct.pack(">Q", len(name_b)))
        hasher.update(name_b)
        hasher.update(struct.pack(">Q", len(value_b)))
        hasher.update(value_b)
    return hasher.hexdigest()


def _listxattr(path: str) -> list[str | bytes]:
    fn = getattr(os, "listxattr", None)
    if fn is None:
        raise MetadataInspectionBlocked("os.listxattr API unavailable")
    try:
        return list(fn(path, follow_symlinks=False))
    except TypeError:
        # Some fakes/platforms may not accept the keyword; still fail closed if wrong.
        raise MetadataInspectionBlocked("os.listxattr requires follow_symlinks=False") from None
    except OSError as exc:
        raise MetadataInspectionBlocked(f"listxattr failed: {type(exc).__name__}") from None


def _getxattr(path: str, name: str | bytes) -> bytes:
    fn = getattr(os, "getxattr", None)
    if fn is None:
        raise MetadataInspectionBlocked("os.getxattr API unavailable")
    try:
        value = fn(path, name, follow_symlinks=False)
    except TypeError:
        raise MetadataInspectionBlocked("os.getxattr requires follow_symlinks=False") from None
    except OSError as exc:
        raise MetadataInspectionBlocked(f"getxattr failed: {type(exc).__name__}") from None
    if not isinstance(value, (bytes, bytearray)):
        raise MetadataInspectionBlocked("getxattr returned non-bytes value")
    return bytes(value)


def _read_xattr_bundle(path: str) -> tuple[int, bool, bool, str]:
    names_before = _listxattr(path)
    pairs: list[tuple[bytes, bytes]] = []
    for raw_name in names_before:
        name_b = _encode_xattr_name(raw_name)
        value = _getxattr(path, raw_name)
        pairs.append((name_b, value))
    names_after = _listxattr(path)
    before_set = sorted(_encode_xattr_name(n) for n in names_before)
    after_set = sorted(_encode_xattr_name(n) for n in names_after)
    if before_set != after_set:
        raise MetadataInspectionBlocked("xattr name-set drift detected")
    # Also require the collected pair names to match the before set exactly.
    pair_names = sorted(name for name, _ in pairs)
    if pair_names != before_set:
        raise MetadataInspectionBlocked("xattr name-set drift detected")
    str_names = {_name_as_str(n) for n in names_before}
    access_present = POSIX_ACL_ACCESS in str_names
    default_present = POSIX_ACL_DEFAULT in str_names
    digest = digest_xattr_pairs(pairs)
    return len(pairs), access_present, default_present, digest


def _join_posix(parent_rel: str, name: str) -> str:
    """Join relative inventory paths without rewriting literal backslashes.

    A Linux filename may contain a literal '\\' character; converting it to
    '/' would collide with a nested directory path of the same visual shape.
    """
    if parent_rel == ".":
        return name
    return f"{parent_rel}/{name}"


def _listdir_sorted(path: str) -> list[str]:
    try:
        names = list(os.listdir(path))
    except OSError as exc:
        raise MetadataInspectionBlocked(f"listdir failed: {type(exc).__name__}") from None
    return sorted(names, key=lambda n: os.fsencode(n))


def _lstat(path: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise MetadataInspectionBlocked(f"lstat failed: {type(exc).__name__}") from None


def _readlink(path: str) -> str:
    try:
        target = os.readlink(path)
    except OSError as exc:
        raise MetadataInspectionBlocked(f"readlink failed: {type(exc).__name__}") from None
    if isinstance(target, bytes):
        return os.fsdecode(target)
    return str(target)


def _inspect_entry(
    *,
    abs_path: str,
    rel_path: str,
    root_device: int,
) -> dict[str, Any]:
    st_before = _lstat(abs_path)
    identity_before = _stat_identity(st_before)
    if int(st_before.st_dev) != root_device:
        raise MetadataInspectionBlocked("device boundary crossed or device drift")

    obj_type = _object_type(int(st_before.st_mode))
    symlink_target: str | None = None
    if obj_type == "symlink":
        symlink_target = _readlink(abs_path)

    xattr_count, acl_access, acl_default, xattr_digest = _read_xattr_bundle(abs_path)

    st_after = _lstat(abs_path)
    identity_after = _stat_identity(st_after)
    if identity_before != identity_after:
        raise MetadataInspectionBlocked("per-entry stat drift detected")

    nlink = int(st_after.st_nlink)
    hard_link_group: str | None
    if nlink > 1:
        hard_link_group = f"{int(st_after.st_dev)}:{int(st_after.st_ino)}"
    else:
        hard_link_group = None

    return {
        "relative_path": rel_path,
        "object_type": obj_type,
        "apparent_size": int(st_after.st_size),
        "allocated_blocks": int(st_after.st_blocks),
        "mtime_ns": int(st_after.st_mtime_ns),
        "ctime_ns": int(st_after.st_ctime_ns),
        "inode": int(st_after.st_ino),
        "device": int(st_after.st_dev),
        "uid": int(st_after.st_uid),
        "gid": int(st_after.st_gid),
        "mode": int(st_after.st_mode),
        "symlink_target": symlink_target,
        "hard_link_group": hard_link_group,
        "xattr_count": xattr_count,
        "posix_acl_access_present": acl_access,
        "posix_acl_default_present": acl_default,
        "xattr_digest": xattr_digest,
    }


def inspect_posix_metadata(
    *,
    root: str,
    expected_device: int,
    expected_inode: int,
    max_entries: int,
) -> dict[str, Any]:
    """Return a deterministic metadata inventory or raise MetadataInspectionBlocked."""
    expected_device = _require_non_negative_int("expected_device", expected_device)
    expected_inode = _require_positive_int("expected_inode", expected_inode)
    max_entries = _require_positive_int("max_entries", max_entries)

    if not isinstance(root, str) or not _is_absolute_path(root):
        raise MetadataInspectionBlocked("root must be an absolute path")

    # Reject trailing slash variants inconsistently; normalize only for joins.
    root_path = root
    if root_path != "/" and root_path.endswith(("/", "\\")):
        root_path = root_path.rstrip("/\\")
        if not root_path:
            root_path = "/"

    euid = geteuid()
    if euid != 0:
        raise MetadataInspectionBlocked("effective UID must be zero (root privilege required)")

    root_st = _lstat(root_path)
    if stat.S_ISLNK(int(root_st.st_mode)):
        raise MetadataInspectionBlocked("root must be a real directory, not a symlink")
    if not stat.S_ISDIR(int(root_st.st_mode)):
        raise MetadataInspectionBlocked("root must be a directory")
    if int(root_st.st_dev) != expected_device:
        raise MetadataInspectionBlocked("root device does not match expected_device")
    if int(root_st.st_ino) != expected_inode:
        raise MetadataInspectionBlocked("root inode does not match expected_inode")

    root_identity = _stat_identity(root_st)
    root_device = int(root_st.st_dev)

    entries: list[dict[str, Any]] = []

    def add_entry(abs_path: str, rel_path: str) -> dict[str, Any]:
        if len(entries) >= max_entries:
            raise MetadataInspectionBlocked("max_entries overflow")
        record = _inspect_entry(abs_path=abs_path, rel_path=rel_path, root_device=root_device)
        entries.append(record)
        return record

    root_record = add_entry(root_path, ".")
    if root_record["object_type"] != "directory":
        raise MetadataInspectionBlocked("root must be a directory")

    def walk_directory(dir_abs: str, dir_rel: str, dir_identity: tuple[Any, ...]) -> None:
        # Deterministic DFS preorder; never follow or traverse symlinks.
        for name in _listdir_sorted(dir_abs):
            if dir_abs.endswith("/"):
                child_abs = dir_abs + name
            else:
                child_abs = dir_abs + "/" + name
            child_rel = _join_posix(dir_rel, name)
            if len(entries) >= max_entries:
                raise MetadataInspectionBlocked("max_entries overflow")
            record = add_entry(child_abs, child_rel)
            if record["object_type"] == "directory":
                # Identity baseline immediately before recursive traversal.
                child_identity = _stat_identity(_lstat(child_abs))
                walk_directory(child_abs, child_rel, child_identity)

        # Re-bracket this directory after its descendants are walked. A
        # descendant create/delete can change directory identity metadata
        # without touching the root directory.
        try:
            dir_after = _lstat(dir_abs)
        except MetadataInspectionBlocked as exc:
            raise MetadataInspectionBlocked(
                "directory disappeared or became unreadable after traversal"
            ) from exc
        if _stat_identity(dir_after) != dir_identity:
            raise MetadataInspectionBlocked("directory stat drift detected after traversal")

    walk_directory(root_path, ".", root_identity)

    # Whole-root stability after full traversal (explicit root pin).
    root_after = _lstat(root_path)
    if _stat_identity(root_after) != root_identity:
        raise MetadataInspectionBlocked("root stat drift detected after traversal")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": PASS_STATUS,
        "root": {
            "path": root,
            "device": expected_device,
            "inode": expected_inode,
        },
        "effective_uid": euid,
        "entry_count": len(entries),
        "entries": entries,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def build_blocked_result(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "reason": reason.replace("\n", " ")[:500],
        "entry_count": 0,
        "entries": [],
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


class _BlockedArgumentParser(argparse.ArgumentParser):
    """Convert argparse validation failures into MetadataInspectionBlocked.

    Does not surface raw invalid tokens (argparse messages may echo them).
    Normal --help still exits 0 via ArgumentParser.exit.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        raise MetadataInspectionBlocked("CLI argument validation failed")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _BlockedArgumentParser(
        prog="inspect_posix_metadata",
        description=(
            "Fail-closed C05 non-secret POSIX metadata inventory reader. "
            "Does not read file contents. Intended for Kind-node use only after "
            "separate authorization."
        ),
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Absolute POSIX root path to inventory (must be a real directory, not a symlink).",
    )
    parser.add_argument(
        "--expected-device",
        required=True,
        type=int,
        help="Caller-pinned st_dev for the root (non-negative integer).",
    )
    parser.add_argument(
        "--expected-inode",
        required=True,
        type=int,
        help="Caller-pinned st_ino for the root (positive integer).",
    )
    parser.add_argument(
        "--max-entries",
        required=True,
        type=int,
        help="Hard upper bound on inventory entries including the root.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        if args.expected_device < 0:
            raise MetadataInspectionBlocked("expected_device must be a non-negative integer")
        if args.expected_inode < 1:
            raise MetadataInspectionBlocked("expected_inode must be a positive integer")
        if args.max_entries < 1:
            raise MetadataInspectionBlocked("max_entries must be a positive integer")
        result = inspect_posix_metadata(
            root=args.root,
            expected_device=args.expected_device,
            expected_inode=args.expected_inode,
            max_entries=args.max_entries,
        )
        sys.stdout.write(json.dumps(result, separators=(",", ":"), ensure_ascii=True) + "\n")
        return 0
    except MetadataInspectionBlocked as exc:
        blocked = build_blocked_result(exc.reason)
        sys.stdout.write(json.dumps(blocked, separators=(",", ":"), ensure_ascii=True) + "\n")
        return 1
    except SystemExit as exc:
        # Preserve argparse --help (exit 0). Convert any other SystemExit from
        # the parser into the same bounded blocked JSON contract.
        code = exc.code
        if code in (0, None):
            raise
        blocked = build_blocked_result("CLI argument validation failed")
        sys.stdout.write(json.dumps(blocked, separators=(",", ":"), ensure_ascii=True) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
