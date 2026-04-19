from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the SHA-256 manifest inside a backup.")
    parser.add_argument("backup", help="Path to the .tar.gz backup archive")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_all(archive: tarfile.TarFile, extracted_root: Path) -> None:
    try:
        archive.extractall(extracted_root, filter="data")  # noqa: S202
    except TypeError:  # pragma: no cover
        archive.extractall(extracted_root)  # noqa: S202


def verify_backup(backup_path: str | Path) -> dict:
    archive_path = Path(backup_path).expanduser().resolve()
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    extracted_root = Path(tempfile.mkdtemp(prefix="agentflow-verify-backup-"))
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            _extract_all(archive, extracted_root)

        manifest_path = extracted_root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("manifest.json not found in backup archive.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files", [])
        if not files:
            raise ValueError("Backup manifest is empty.")

        for item in files:
            file_path = extracted_root / item["archive_path"]
            if not file_path.exists():
                raise FileNotFoundError(f"Missing archived file: {item['archive_path']}")
            expected_size = item["size_bytes"]
            actual_size = file_path.stat().st_size
            if actual_size != expected_size:
                raise ValueError(
                    "Size mismatch for "
                    f"{item['archive_path']}: expected {expected_size}, got {actual_size}"
                )
            expected_hash = item["sha256"]
            actual_hash = _sha256(file_path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"SHA-256 mismatch for {item['archive_path']}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

        return {
            "archive": str(archive_path),
            "timestamp": manifest.get("timestamp"),
            "file_count": len(files),
            "duckdb_files": manifest.get("duckdb_files", []),
            "config_files": manifest.get("config_files", []),
        }
    finally:
        shutil.rmtree(extracted_root, ignore_errors=True)


def main() -> int:
    args = build_parser().parse_args()
    result = verify_backup(args.backup)
    print(f"Verified backup: {result['archive']}")
    print(f"Timestamp: {result['timestamp']}")
    print(f"Files: {result['file_count']}")
    print(f"DuckDB files: {', '.join(result['duckdb_files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
