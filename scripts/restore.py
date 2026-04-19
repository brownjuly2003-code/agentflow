from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restore a backup archive into a project root.")
    parser.add_argument("--backup", required=True, help="Path to the .tar.gz backup archive")
    parser.add_argument("--target-root", default=str(PROJECT_ROOT))
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


def _extract_archive(backup_path: Path) -> tuple[Path, dict]:
    extracted_root = Path(tempfile.mkdtemp(prefix="agentflow-restore-"))
    with tarfile.open(backup_path, "r:gz") as archive:
        _extract_all(archive, extracted_root)

    manifest_path = extracted_root / "manifest.json"
    if not manifest_path.exists():
        shutil.rmtree(extracted_root, ignore_errors=True)
        raise FileNotFoundError("manifest.json not found in backup archive.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        file_path = extracted_root / item["archive_path"]
        if not file_path.exists():
            shutil.rmtree(extracted_root, ignore_errors=True)
            raise FileNotFoundError(f"Missing archived file: {item['archive_path']}")
        if file_path.stat().st_size != item["size_bytes"]:
            shutil.rmtree(extracted_root, ignore_errors=True)
            raise ValueError(f"Size mismatch for {item['archive_path']}")
        if _sha256(file_path) != item["sha256"]:
            shutil.rmtree(extracted_root, ignore_errors=True)
            raise ValueError(f"SHA-256 mismatch for {item['archive_path']}")

    return extracted_root, manifest


def _expected_tenant_schemas(tenants_path: Path) -> set[str]:
    if not tenants_path.exists():
        return set()
    content = tenants_path.read_text(encoding="utf-8")
    return {
        match.group(1).strip()
        for match in re.finditer(
            r'^\s*duckdb_schema:\s*["\']?([^"\']+)["\']?\s*$',
            content,
            flags=re.MULTILINE,
        )
    }


def _smoke_test(target_root: Path, manifest: dict) -> tuple[int, int]:
    expected_config_files = [
        target_root / Path(item["restore_path"])
        for item in manifest.get("files", [])
        if item["category"] == "config"
    ]
    missing_config = [path.as_posix() for path in expected_config_files if not path.exists()]
    if missing_config:
        raise FileNotFoundError(f"Missing restored config files: {', '.join(missing_config)}")

    checked_databases = 0
    expected_tenants = _expected_tenant_schemas(target_root / "config" / "tenants.yaml")
    for item in manifest.get("files", []):
        if item["category"] != "duckdb":
            continue
        db_path = target_root / Path(item["restore_path"])
        if not db_path.exists():
            raise FileNotFoundError(f"Restored database not found: {db_path}")

        connection = duckdb.connect(str(db_path), read_only=True)
        try:
            connection.execute("SELECT 1").fetchone()
            if item.get("role") == "pipeline" and expected_tenants:
                existing_schemas = {
                    row[0]
                    for row in connection.execute(
                        "SELECT schema_name FROM information_schema.schemata"
                    ).fetchall()
                }
                missing_schemas = sorted(expected_tenants - existing_schemas)
                if missing_schemas:
                    raise ValueError(
                        "Missing tenant schemas after restore: " + ", ".join(missing_schemas)
                    )
            if item.get("role") == "usage":
                usage_table = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'main' AND table_name = 'api_usage'
                    """
                ).fetchone()
                if usage_table is None or usage_table[0] == 0:
                    raise ValueError("api_usage table not found in restored usage database.")
        finally:
            connection.close()
        checked_databases += 1

    if checked_databases == 0:
        raise ValueError("Restore smoke test did not validate any DuckDB databases.")
    return checked_databases, len(expected_config_files)


def restore(backup_path: str | Path, target_root: str | Path = PROJECT_ROOT) -> dict:
    archive_path = Path(backup_path).expanduser().resolve()
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    destination_root = Path(target_root).expanduser().resolve()
    extracted_root, manifest = _extract_archive(archive_path)
    try:
        for item in manifest.get("files", []):
            source = extracted_root / item["archive_path"]
            destination = destination_root / Path(item["restore_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        checked_databases, checked_config_files = _smoke_test(destination_root, manifest)
        return {
            "archive": str(archive_path),
            "target_root": str(destination_root),
            "checked_databases": checked_databases,
            "checked_config_files": checked_config_files,
        }
    finally:
        shutil.rmtree(extracted_root, ignore_errors=True)


def main() -> int:
    args = build_parser().parse_args()
    result = restore(args.backup, target_root=args.target_root)
    print(f"Restored backup: {result['archive']}")
    print(f"Target root: {result['target_root']}")
    print(
        "Smoke test: "
        f"{result['checked_databases']} DuckDB files, "
        f"{result['checked_config_files']} config files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
