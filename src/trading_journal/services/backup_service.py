"""Local data portability: CSV/JSON export, zip backup, and conservative restore.

Design goals:
* **Local-first** — everything stays on disk; nothing is uploaded anywhere.
* **Non-destructive restore** — restore validates the archive first and (by
  default) snapshots the current database before overwriting it.
* **Faithful** — a backup zip bundles a copy of the SQLite database *plus* CSV and
  JSON exports and a ``manifest.json`` describing what it contains.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..models import Account, AccountSnapshot, DailyReview, SyncRun, Trade

# Logical tables included in CSV/JSON exports, in dependency order.
_EXPORT_MODELS = {
    "accounts": Account,
    "trades": Trade,
    "account_snapshots": AccountSnapshot,
    "daily_reviews": DailyReview,
    "sync_runs": SyncRun,
}

MANIFEST_NAME = "manifest.json"
BACKUP_FORMAT = "trading-journal-backup/1"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _table_dataframe(session: Session, model: type) -> pd.DataFrame:
    columns = [c.name for c in model.__table__.columns]
    rows = session.execute(select(model)).scalars().all()
    return pd.DataFrame([{c: getattr(row, c) for c in columns} for row in rows], columns=columns)


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def export_csv(session: Session, out_dir: str | Path) -> list[Path]:
    """Write one CSV per logical table into ``out_dir``. Returns the file paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, model in _EXPORT_MODELS.items():
        df = _table_dataframe(session, model)
        path = out / f"{name}.csv"
        df.to_csv(path, index=False)
        paths.append(path)
    return paths


def build_export_dict(session: Session) -> dict:
    """Build the in-memory JSON-export structure (manifest + all table rows)."""
    data: dict = {
        "manifest": {
            "app": "trading_journal",
            "version": __version__,
            "format": BACKUP_FORMAT,
            "created_at": datetime.now(UTC).isoformat(),
        },
        "tables": {},
    }
    counts: dict[str, int] = {}
    for name, model in _EXPORT_MODELS.items():
        df = _table_dataframe(session, model)
        data["tables"][name] = df.to_dict(orient="records")
        counts[name] = int(len(df))
    data["manifest"]["counts"] = counts
    return data


def export_json(session: Session, out_dir: str | Path, filename: str = "export.json") -> Path:
    """Write a single JSON file containing all logical tables + a manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    payload = build_export_dict(session)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


# ---------------------------------------------------------------------------
# Backup (zip)
# ---------------------------------------------------------------------------
def sqlite_path_from_session(session: Session) -> Path | None:
    """Return the on-disk SQLite file for this session, or None if not applicable."""
    url = session.get_bind().url
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def _build_manifest(session: Session, db_filename: str | None, files: list[str]) -> dict:
    counts = {
        name: int(len(_table_dataframe(session, model))) for name, model in _EXPORT_MODELS.items()
    }
    return {
        "app": "trading_journal",
        "version": __version__,
        "format": BACKUP_FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "database_file": db_filename,
        "counts": counts,
        "files": files,
    }


def create_backup(session: Session, out_dir: str | Path, db_path: str | Path | None = None) -> Path:
    """Create a timestamped zip backup and return its path.

    The archive contains a copy of the SQLite database (when available), CSV and
    JSON exports, and a ``manifest.json``. The DB copy reflects the last committed
    state, so callers should commit any pending writes before backing up.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    resolved_db = Path(db_path) if db_path is not None else sqlite_path_from_session(session)
    db_filename = resolved_db.name if resolved_db and resolved_db.exists() else None

    files = [f"{name}.csv" for name in _EXPORT_MODELS] + ["export.json", MANIFEST_NAME]
    if db_filename:
        files.insert(0, db_filename)

    manifest = _build_manifest(session, db_filename, files)
    export_payload = build_export_dict(session)

    zip_path = out / f"trading_journal_backup_{_timestamp()}.zip"
    with ZipFile(zip_path, "w") as zf:
        if db_filename and resolved_db is not None:
            zf.write(resolved_db, arcname=db_filename)
        for name, model in _EXPORT_MODELS.items():
            df = _table_dataframe(session, model)
            zf.writestr(f"{name}.csv", df.to_csv(index=False))
        zf.writestr("export.json", json.dumps(export_payload, indent=2, default=str))
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, default=str))
    return zip_path


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
@dataclass
class BackupInfo:
    """Validation summary for a backup archive."""

    valid: bool
    files: list[str] = field(default_factory=list)
    database_file: str | None = None
    manifest: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    """Outcome of a restore operation."""

    restored: bool
    target: Path
    backup_of_current: Path | None
    database_file: str | None
    message: str


def _first_db_member(names: list[str]) -> str | None:
    for name in names:
        if name.endswith((".db", ".sqlite", ".sqlite3")):
            return name
    return None


def inspect_backup(zip_path: str | Path) -> BackupInfo:
    """Validate a backup archive without modifying anything."""
    path = Path(zip_path)
    if not path.exists():
        return BackupInfo(valid=False, problems=[f"file not found: {path}"])
    try:
        with ZipFile(path) as zf:
            names = zf.namelist()
            manifest: dict = {}
            problems: list[str] = []
            if MANIFEST_NAME in names:
                try:
                    manifest = json.loads(zf.read(MANIFEST_NAME))
                except (ValueError, TypeError):
                    problems.append("manifest.json is not valid JSON")
            else:
                problems.append("missing manifest.json")
            db_member = _first_db_member(names)
            if db_member is None:
                problems.append("archive contains no database (.db) file")
    except Exception as exc:  # noqa: BLE001 - report any bad/corrupt zip cleanly
        return BackupInfo(valid=False, problems=[f"could not read archive: {exc}"])

    return BackupInfo(
        valid=not problems,
        files=names,
        database_file=db_member,
        manifest=manifest,
        problems=problems,
    )


def restore_backup(
    zip_path: str | Path, target_db_path: str | Path, make_backup: bool = True
) -> RestoreResult:
    """Restore the SQLite database from a backup archive (conservative).

    Validates the archive first, snapshots the current database (unless
    ``make_backup=False``), then replaces it. Never overwrites without first
    passing validation.
    """
    info = inspect_backup(zip_path)
    if not info.valid or info.database_file is None:
        raise ValueError("invalid backup archive: " + "; ".join(info.problems))

    target = Path(target_db_path)
    backup_of_current: Path | None = None
    if make_backup and target.exists():
        backup_of_current = target.with_name(f"{target.name}.pre-restore-{_timestamp()}")
        shutil.copy2(target, backup_of_current)

    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path) as zf:
        member: ZipInfo = zf.getinfo(info.database_file)
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)

    return RestoreResult(
        restored=True,
        target=target,
        backup_of_current=backup_of_current,
        database_file=info.database_file,
        message=(
            f"Restored {info.database_file} into {target}."
            + (f" Previous DB saved to {backup_of_current.name}." if backup_of_current else "")
        ),
    )
