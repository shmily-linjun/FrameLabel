"""Machine-scoped application state database (fork.53).

One SQLite file per user holds the operator accounts, the known-dataset
registry and the registry audit events.  Before fork.53 the file was called
``operators.db``; it was renamed to ``platform.db`` because it now stores
dataset state as well (see :mod:`anylabeling.services.identity.session` for the
path and the migration of the old file).

The schema version is stored as text in ``meta.schema_version`` (not
``PRAGMA user_version``).  Every statement is idempotent
(``CREATE ... IF NOT EXISTS``), so an existing pre-fork.53 database is upgraded
in place: the ``operator`` and ``meta`` tables stay untouched and the new
registry tables are added.
"""

from __future__ import annotations

import sqlite3

#: Bumped when the app-state schema changes.  ``"2"`` added the dataset
#: registry and its audit table (fork.53).
APP_SCHEMA_VERSION = "2"

APP_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS operator (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        password_iterations INTEGER NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT NOT NULL UNIQUE,
        db_path TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        root_path TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'active'
            CHECK (state IN ('active', 'missing', 'deleted')),
        delete_mode TEXT NOT NULL DEFAULT '',
        backup_path TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_opened_at TEXT NOT NULL DEFAULT '',
        last_opened_by INTEGER REFERENCES operator(id) ON DELETE SET NULL,
        deleted_at TEXT NOT NULL DEFAULT '',
        deleted_by INTEGER REFERENCES operator(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_dataset_registry_path
        ON dataset_registry(db_path COLLATE NOCASE)
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_registry_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        registry_id INTEGER,
        uuid TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        operator_id INTEGER REFERENCES operator(id) ON DELETE SET NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_dataset_registry_event_uuid
        ON dataset_registry_event(uuid, id)
    """,
)


def ensure_app_schema(connection: sqlite3.Connection) -> None:
    """Create/upgrade the app-state schema in ``connection`` (idempotent)."""

    for statement in APP_SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", APP_SCHEMA_VERSION),
    )
