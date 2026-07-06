"""Application configuration.

Configuration is intentionally small and environment-driven so the app works
locally with zero setup while still allowing overrides via a ``.env`` file or
real environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# The repository root is three parents up from this file:
# src/trading_journal/config.py -> src/trading_journal -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a simple ``.env`` file if present.

    This is a tiny, dependency-free parser. It only sets keys that are not
    already defined in the environment so real environment variables win.
    """
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Resolved application settings."""

    data_dir: Path
    db_path: Path
    database_url: str
    sql_echo: bool
    sample_data_dir: Path

    @property
    def demo_account_name(self) -> str:
        return "Demo Account"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings, loading ``.env`` on first access."""
    _load_dotenv(REPO_ROOT / ".env")

    data_dir = Path(os.environ.get("TRADING_JOURNAL_DATA_DIR", str(REPO_ROOT / "data")))
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir

    db_name = os.environ.get("TRADING_JOURNAL_DB_NAME", "trading_journal.db")
    db_path = data_dir / db_name

    explicit_url = os.environ.get("TRADING_JOURNAL_DATABASE_URL")
    database_url = explicit_url or f"sqlite:///{db_path}"

    sql_echo = _as_bool(os.environ.get("TRADING_JOURNAL_SQL_ECHO"), default=False)

    sample_data_dir = REPO_ROOT / "sample_data"

    # Make sure the data directory exists so SQLite can create the file.
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        database_url=database_url,
        sql_echo=sql_echo,
        sample_data_dir=sample_data_dir,
    )
