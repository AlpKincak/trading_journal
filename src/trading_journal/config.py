"""Application configuration.

Configuration is intentionally small and environment-driven so the app works
locally with zero setup while still allowing overrides via a ``.env`` file or
real environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# TradeLocker (Phase 2) — read-only sync configuration.
#
# These settings are ONLY consulted when a TradeLocker command/button is used.
# Normal local dashboard use never requires them. Credentials live in the
# environment / .env and are NEVER written to the database or logged.
# ---------------------------------------------------------------------------
TRADELOCKER_DEMO_BASE_URL = "https://demo.tradelocker.com"
TRADELOCKER_LIVE_BASE_URL = "https://live.tradelocker.com"


@dataclass(frozen=True)
class TradeLockerSettings:
    """Resolved TradeLocker connector settings.

    ``password`` is a secret: it is excluded from ``repr`` so it never leaks
    into logs, tracebacks, or debug output.
    """

    enabled: bool
    environment: str  # "demo" | "live"
    base_url: str  # resolved base (no /backend-api suffix)
    email: str | None
    server: str | None
    account_id: str | None
    acc_num: str | None
    lookback_days: int
    request_timeout_seconds: int
    dry_run: bool
    password: str | None = field(repr=False, default=None)

    @property
    def api_base_url(self) -> str:
        """Base URL for backend API calls (``<base_url>/backend-api``)."""
        return f"{self.base_url.rstrip('/')}/backend-api"

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password and self.server)

    @property
    def masked_email(self) -> str:
        """Email with the local part partly masked (safe for display)."""
        if not self.email or "@" not in self.email:
            return "—"
        local, _, domain = self.email.partition("@")
        head = local[:2]
        return f"{head}{'*' * max(1, len(local) - 2)}@{domain}"

    def missing_credential_fields(self) -> list[str]:
        missing = []
        if not self.email:
            missing.append("TRADELOCKER_EMAIL")
        if not self.password:
            missing.append("TRADELOCKER_PASSWORD")
        if not self.server:
            missing.append("TRADELOCKER_SERVER")
        return missing


def _resolve_tradelocker_base_url(environment: str, override: str | None) -> str:
    if override:
        return override.strip().rstrip("/")
    if environment == "live":
        return TRADELOCKER_LIVE_BASE_URL
    return TRADELOCKER_DEMO_BASE_URL


def _as_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(float(value.strip()))
    except (TypeError, ValueError):
        return default


def get_tradelocker_settings() -> TradeLockerSettings:
    """Read TradeLocker settings from the environment (loading ``.env`` first).

    Intentionally *not* cached so tests can vary the environment freely and so a
    freshly-edited ``.env`` is picked up without restarting a long-running
    dashboard. Reading a handful of env vars is cheap.
    """
    _load_dotenv(REPO_ROOT / ".env")

    environment = (os.environ.get("TRADELOCKER_ENVIRONMENT") or "demo").strip().lower()
    if environment not in {"demo", "live"}:
        environment = "demo"

    override = os.environ.get("TRADELOCKER_BASE_URL")
    base_url = _resolve_tradelocker_base_url(environment, override)

    def _clean(key: str) -> str | None:
        value = os.environ.get(key)
        if value is None:
            return None
        value = value.strip()
        return value or None

    return TradeLockerSettings(
        enabled=_as_bool(os.environ.get("TRADELOCKER_ENABLED"), default=False),
        environment=environment,
        base_url=base_url,
        email=_clean("TRADELOCKER_EMAIL"),
        password=_clean("TRADELOCKER_PASSWORD"),
        server=_clean("TRADELOCKER_SERVER"),
        account_id=_clean("TRADELOCKER_ACCOUNT_ID"),
        acc_num=_clean("TRADELOCKER_ACC_NUM"),
        lookback_days=_as_int(os.environ.get("TRADELOCKER_SYNC_LOOKBACK_DAYS"), default=90),
        request_timeout_seconds=_as_int(
            os.environ.get("TRADELOCKER_REQUEST_TIMEOUT_SECONDS"), default=30
        ),
        dry_run=_as_bool(os.environ.get("TRADELOCKER_DRY_RUN"), default=True),
    )
