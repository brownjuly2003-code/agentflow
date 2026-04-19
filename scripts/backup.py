from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import duckdb

DEFAULT_PIPELINE_DB = "agentflow_demo.duckdb"
DEFAULT_USAGE_DB = "agentflow_api.duckdb"
DEFAULT_RPO_TARGET_SECONDS = 24 * 60 * 60
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class BackupFile:
    archive_path: str
    restore_path: str
    category: str
    role: str | None
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class BackupManifest:
    timestamp: str
    created_at: str
    archive_name: str
    project_root: str
    duckdb_size_bytes: int
    duckdb_files: list[str]
    config_files: list[str]
    files: list[BackupFile]
    rpo_target_seconds: int
    rpo_achieved_seconds: int

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["files"] = [asdict(item) for item in self.files]
        return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a timestamped backup archive for DuckDB and config.",
    )
    parser.add_argument("--output", required=True, help="Local directory or s3://bucket/prefix/")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--duckdb-path", default=None)
    parser.add_argument("--usage-db-path", default=None)
    parser.add_argument("--rpo-target-seconds", type=int, default=DEFAULT_RPO_TARGET_SECONDS)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(project_root: Path, value: str | None, default: str) -> Path:
    raw = Path(value or default).expanduser()
    return raw if raw.is_absolute() else (project_root / raw)


def _resolve_usage_db_path(
    project_root: Path,
    pipeline_db_path: Path,
    explicit_usage_path: str | None,
) -> Path:
    if explicit_usage_path is not None:
        return _resolve_path(project_root, explicit_usage_path, explicit_usage_path)
    env_usage_path = os.getenv("AGENTFLOW_USAGE_DB_PATH")
    if env_usage_path:
        return _resolve_path(project_root, env_usage_path, env_usage_path)
    derived = pipeline_db_path.with_name(
        f"{pipeline_db_path.stem}_api{pipeline_db_path.suffix or '.duckdb'}"
    )
    if derived.exists():
        return derived
    return project_root / DEFAULT_USAGE_DB


def _restore_path(project_root: Path, source_path: Path, fallback_dir: str) -> str:
    try:
        return source_path.relative_to(project_root).as_posix()
    except ValueError:
        return f"{fallback_dir}/{source_path.name}"


def _checkpoint_duckdb(db_path: Path) -> None:
    if not db_path.exists():
        return
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute("CHECKPOINT")
    finally:
        connection.close()


def _duckdb_sources(project_root: Path, pipeline_db_path: Path, usage_db_path: Path) -> list[dict]:
    sources: list[dict] = []
    seen_paths: set[Path] = set()
    for db_path, role in ((pipeline_db_path, "pipeline"), (usage_db_path, "usage")):
        if db_path in seen_paths or not db_path.exists():
            continue
        _checkpoint_duckdb(db_path)
        seen_paths.add(db_path)
        sources.append({
            "path": db_path,
            "archive_path": _restore_path(project_root, db_path, "data"),
            "role": role,
            "category": "duckdb",
        })
        wal_path = db_path.with_name(f"{db_path.name}.wal")
        if wal_path.exists():
            sources.append({
                "path": wal_path,
                "archive_path": _restore_path(project_root, wal_path, "data"),
                "role": role,
                "category": "duckdb_wal",
            })
    return sources


def _config_sources(project_root: Path) -> list[dict]:
    config_dir = project_root / "config"
    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")
    items = []
    for file_path in sorted(path for path in config_dir.rglob("*") if path.is_file()):
        items.append({
            "path": file_path,
            "archive_path": file_path.relative_to(project_root).as_posix(),
            "role": None,
            "category": "config",
        })
    return items


def _rpo_achieved_seconds(duckdb_sources: list[dict]) -> int:
    timestamps = [
        datetime.fromtimestamp(item["path"].stat().st_mtime, tz=UTC)
        for item in duckdb_sources
        if item["category"] == "duckdb"
    ]
    if not timestamps:
        return 0
    newest = max(timestamps)
    return max(int((datetime.now(UTC) - newest).total_seconds()), 0)


def _archive_path(output: str, timestamp: str) -> tuple[Path, str | None]:
    archive_name = f"agentflow-backup-{timestamp}.tar.gz"
    if output.startswith("s3://"):
        return Path(tempfile.gettempdir()) / archive_name, output

    output_dir = Path(output).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name
    counter = 1
    while archive_path.exists():
        archive_path = output_dir / f"agentflow-backup-{timestamp}-{counter}.tar.gz"
        counter += 1
    return archive_path, None


def _upload_to_s3(local_archive: Path, destination: str) -> str:
    try:
        import boto3
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "S3 upload requested, but boto3 is not installed. Install the cloud extras first."
        ) from exc

    parsed = urlparse(destination)
    bucket = parsed.netloc
    key_prefix = parsed.path.lstrip("/")
    key_prefix = key_prefix.rstrip("/")
    key = f"{key_prefix}/{local_archive.name}" if key_prefix else local_archive.name
    boto3.client("s3").upload_file(str(local_archive), bucket, key)
    return f"s3://{bucket}/{key}"


def backup(
    output_dir: str,
    project_root: str | Path = PROJECT_ROOT,
    duckdb_path: str | None = None,
    usage_db_path: str | None = None,
    rpo_target_seconds: int = DEFAULT_RPO_TARGET_SECONDS,
) -> tuple[BackupManifest, str]:
    root = Path(project_root).expanduser().resolve()
    pipeline_db_path = _resolve_path(
        root,
        duckdb_path or os.getenv("DUCKDB_PATH"),
        DEFAULT_PIPELINE_DB,
    )
    usage_path = _resolve_usage_db_path(root, pipeline_db_path, usage_db_path)

    duckdb_sources = _duckdb_sources(root, pipeline_db_path, usage_path)
    if not duckdb_sources:
        raise FileNotFoundError(
            "No DuckDB files found to back up. "
            f"Checked {pipeline_db_path} and {usage_path}."
        )

    config_sources = _config_sources(root)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path, remote_destination = _archive_path(output_dir, timestamp)
    staging_root = Path(tempfile.mkdtemp(prefix=f"agentflow-backup-{timestamp}-"))
    created_at = datetime.now(UTC).isoformat()

    try:
        files: list[BackupFile] = []
        for item in [*duckdb_sources, *config_sources]:
            relative_path = Path(item["archive_path"])
            target_path = staging_root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item["path"], target_path)
            files.append(
                BackupFile(
                    archive_path=relative_path.as_posix(),
                    restore_path=relative_path.as_posix(),
                    category=item["category"],
                    role=item["role"],
                    size_bytes=target_path.stat().st_size,
                    sha256=_sha256(target_path),
                )
            )

        manifest = BackupManifest(
            timestamp=timestamp,
            created_at=created_at,
            archive_name=archive_path.name,
            project_root=str(root),
            duckdb_size_bytes=sum(
                item.size_bytes for item in files if item.category.startswith("duckdb")
            ),
            duckdb_files=[
                item.archive_path for item in files if item.category == "duckdb"
            ],
            config_files=[
                item.archive_path for item in files if item.category == "config"
            ],
            files=files,
            rpo_target_seconds=rpo_target_seconds,
            rpo_achieved_seconds=_rpo_achieved_seconds(duckdb_sources),
        )
        (staging_root / "manifest.json").write_text(
            json.dumps(manifest.to_dict(), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        with tarfile.open(archive_path, "w:gz") as archive:
            for path in sorted(staging_root.iterdir()):
                archive.add(path, arcname=path.name)

        final_location = str(archive_path)
        if remote_destination is not None:
            final_location = _upload_to_s3(archive_path, remote_destination)

        return manifest, final_location
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def main() -> int:
    args = build_parser().parse_args()
    manifest, archive_path = backup(
        output_dir=args.output,
        project_root=args.project_root,
        duckdb_path=args.duckdb_path,
        usage_db_path=args.usage_db_path,
        rpo_target_seconds=args.rpo_target_seconds,
    )
    print(f"Backup archive: {archive_path}")
    print(f"DuckDB files: {', '.join(manifest.duckdb_files)}")
    print(f"Config files: {len(manifest.config_files)}")
    print(f"SHA-256 manifest: {len(manifest.files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
