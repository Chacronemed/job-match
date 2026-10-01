import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_MIGRATIONS = Path(__file__).parent.parent.parent.parent / "migrations"


class Database:
    """Opens a SQLite connection and applies numbered migrations on first use."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        migrations_dir: Path | None = None,
    ) -> None:
        self._path = str(path)
        self._migrations_dir = Path(migrations_dir) if migrations_dir else _DEFAULT_MIGRATIONS
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn  # type: ignore[return-value]

    def connect(self) -> "Database":
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._conn = conn
        self._apply_migrations()
        return self

    def _apply_migrations(self) -> int:
        conn = self._conn
        # Bootstrap: schema_version must exist before we can check it.
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
        files = sorted(
            self._migrations_dir.glob("*.sql"),
            key=lambda p: int(p.stem[:4]),
        )
        count = 0
        for f in files:
            version = int(f.stem[:4])
            if version in applied:
                continue
            conn.executescript(f.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            conn.commit()
            count += 1
        return count

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self.connect()

    def __exit__(self, *_: object) -> None:
        self.close()
