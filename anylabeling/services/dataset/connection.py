"""Opening, creating and transacting a dataset SQLite database.

The database lives at ``<dataset root>/xanylabeling.db``.  This module only
owns connection-level concerns: PRAGMAs, schema version/application id,
transactions and online backup.  Table-level rules live in
:mod:`anylabeling.services.dataset.repository`.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence
from uuid import uuid4

from .errors import DatasetError, DatasetNotFoundError
from .schema import APPLICATION_ID, SCHEMA_SQL, SCHEMA_VERSION

DATABASE_FILENAME = "xanylabeling.db"
SCHEMA_DESCRIPTION = "初始 schema：8 表 3 视图（讨论稿 v0.13）"


class DatasetDatabase:
    """A SQLite connection bound to one dataset."""

    def __init__(self, path: Path, connection: sqlite3.Connection, read_only: bool):
        self.path = Path(path)
        self.connection = connection
        self.read_only = read_only
        self._transaction_depth = 0

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        name: str = "",
        task: str = "",
        description: str = "",
        app_version: str = "",
    ) -> "DatasetDatabase":
        """Create a new dataset database.

        An existing non-empty file is rejected; the caller must choose
        ``open`` (or delete the file explicitly) instead of silently
        overwriting a dataset.
        """

        target = Path(path)
        if target.exists() and target.stat().st_size > 0:
            raise DatasetError(f"dataset database already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(str(target), isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(SCHEMA_SQL)
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.execute("BEGIN")
            connection.execute(
                "INSERT INTO dataset (uuid, name, description, task, app_version) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuid4().hex, name, description, task, app_version),
            )
            connection.execute(
                "INSERT INTO schema_migration (version, description) VALUES (?, ?)",
                (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.close()
            raise
        return cls(target, connection, False)

    @classmethod
    def open_for_reading(cls, path: str | Path) -> "DatasetDatabase":
        """Open for reading, falling back to a normal connection.

        A WAL database that is currently written by the labeling window (or
        another process) can refuse the ``mode=ro`` URI; the fallback keeps
        read-only callers (overview, registry validation, merge sources)
        working instead of reporting a false "cannot open" error.
        """

        try:
            return cls.open(path, read_only=True)
        except Exception:
            return cls.open(path)

    @classmethod
    def open(cls, path: str | Path, *, read_only: bool = False) -> "DatasetDatabase":
        target = Path(path)
        if not target.is_file():
            raise DatasetNotFoundError(f"dataset database not found: {target}")
        if read_only:
            uri = target.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, isolation_level=None)
        else:
            connection = sqlite3.connect(str(target), isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            if not read_only:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
            application_id = connection.execute(
                "PRAGMA application_id"
            ).fetchone()[0]
            if application_id != APPLICATION_ID:
                raise DatasetError(
                    "not a dataset database (application_id="
                    f"{application_id}, expected {APPLICATION_ID})"
                )
            user_version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            if user_version > SCHEMA_VERSION:
                raise DatasetError(
                    "dataset database is newer than this application "
                    f"(user_version={user_version}, supported={SCHEMA_VERSION})"
                )
            if user_version == 0:
                raise DatasetError("dataset database has no schema version")
        except Exception:
            connection.close()
            raise
        return cls(target, connection, read_only)

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            if not self.read_only:
                self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.connection.close()
        self.connection = None

    def __enter__(self) -> "DatasetDatabase":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    # -- transactions / helpers -------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write transaction, nesting as a no-op."""

        if self.read_only:
            raise DatasetError("dataset database is read-only")
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield self.connection
            finally:
                self._transaction_depth -= 1
            return
        self.connection.execute("BEGIN IMMEDIATE")
        self._transaction_depth = 1
        try:
            yield self.connection
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")
        finally:
            self._transaction_depth = 0

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def query(self, sql: str, parameters: Sequence[object] = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, parameters).fetchall()

    def query_one(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Row | None:
        return self.connection.execute(sql, parameters).fetchone()

    def table_counts(self) -> dict[str, int]:
        tables = (
            "dataset",
            "category",
            "image_file",
            "annotation_object",
            "image_tag",
            "object_relation",
            "import_session",
            "schema_migration",
        )
        return {
            table: self.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in tables
        }

    # -- backup ------------------------------------------------------------
    def backup_to(self, target: str | Path) -> Path:
        """Create a consistent online backup (includes WAL content)."""

        destination = Path(target)
        if destination.exists():
            raise DatasetError(f"backup target already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.read_only:
            raise DatasetError("cannot back up a read-only connection")
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        try:
            self.connection.execute("VACUUM INTO ?", (str(destination),))
        except sqlite3.Error:
            if destination.exists():
                destination.unlink()
            backup = sqlite3.connect(str(destination))
            try:
                self.connection.backup(backup)
            finally:
                backup.close()
        return destination
