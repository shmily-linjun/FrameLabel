"""Known-dataset registry (fork.53, T11).

The registry lives in the machine-scoped application-state database
``platform.db`` (see :mod:`anylabeling.services.app_state`): it stores which
dataset databases this installation has opened, their display metadata and
their health state, plus an append-only audit trail of registry actions.

Design notes
------------

* Dataset identity is ``dataset.uuid`` plus the absolute database path; the
  folder/display name never identifies a dataset (two folders can share a
  name, see the design doc §4.7).
* ``state`` is one of ``active``, ``missing`` or ``deleted``.  ``missing``
  means the database disappeared or stopped being a dataset database (the user
  deleted it outside the application); ``deleted`` means it was deleted
  through the dataset center (the audit event records who/when/mode/backup).
* Nothing here imports Qt: the window calls this service, and tests use it
  directly.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import os.path as osp
import sqlite3
import threading
from dataclasses import dataclass

from ..app_state import ensure_app_schema
from ..identity.session import default_database_path
from .connection import DATABASE_FILENAME, DatasetDatabase

#: State of a registry entry.
STATE_ACTIVE = "active"
STATE_MISSING = "missing"
STATE_DELETED = "deleted"
STATES = (STATE_ACTIVE, STATE_MISSING, STATE_DELETED)


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_path(path: object) -> str:
    if not isinstance(path, (str, os.PathLike)):
        raise RegistryError("dataset path must be a path")
    value = str(path)
    if not value.strip():
        raise RegistryError("dataset path must not be empty")
    return osp.abspath(osp.expanduser(value))


class RegistryError(Exception):
    """Base class for registry errors."""


class RegistryEntryNotFoundError(RegistryError):
    """Raised when a registry uuid/path is unknown."""


@dataclass(frozen=True)
class RegistryEntry:
    """One known dataset."""

    id: int
    uuid: str
    db_path: str
    display_name: str
    root_path: str
    state: str
    created_at: str
    last_opened_at: str
    last_opened_by: int | None
    deleted_at: str
    deleted_by: int | None
    delete_mode: str
    backup_path: str


@dataclass(frozen=True)
class DatasetCheck:
    """Result of validating a dataset database on disk."""

    ok: bool
    state: str
    reason: str = ""
    uuid: str = ""
    name: str = ""
    root_path: str = ""
    description: str = ""

    @property
    def root(self) -> str:
        return self.root_path


class RegistryStore:
    """Read/write access to the dataset registry."""

    def __init__(self, db_path: str | None = None):
        self.db_path = _normalize_path(db_path or default_database_path())
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    # -- connections -------------------------------------------------------
    @contextlib.contextmanager
    def _connection(self):
        directory = osp.dirname(self.db_path)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            connection = sqlite3.connect(self.db_path, timeout=5.0)
        except (OSError, sqlite3.Error) as error:
            raise RegistryError(
                f"cannot open the app database '{self.db_path}': {error}"
            ) from error
        try:
            connection.row_factory = sqlite3.Row
            with contextlib.suppress(sqlite3.Error):
                connection.execute("PRAGMA busy_timeout = 5000")
            self._ensure_schema(connection)
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise RegistryError(f"app database error: {error}") from error
        finally:
            connection.close()

    def _ensure_schema(self, connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            ensure_app_schema(connection)
            connection.commit()
            self._schema_ready = True

    # -- validation --------------------------------------------------------
    @staticmethod
    def check_dataset(db_path: str) -> DatasetCheck:
        """Validate ``db_path`` and return its dataset metadata."""

        path = _normalize_path(db_path)
        if not osp.isfile(path):
            return DatasetCheck(False, STATE_MISSING, "数据库文件不存在")
        try:
            database = DatasetDatabase.open(path, read_only=True)
        except Exception as error:  # noqa: BLE001 - surfaced to the window
            return DatasetCheck(
                False, STATE_MISSING, f"无法打开数据库：{error}"
            )
        try:
            application = database.query("PRAGMA application_id")
            if application and int(application[0][0]) != _application_id():
                return DatasetCheck(
                    False, STATE_MISSING, "不是本程序的数据集数据库"
                )
            row = database.query_one(
                "SELECT uuid, name, root_path, description "
                "FROM dataset ORDER BY id LIMIT 1"
            )
            if row is None:
                return DatasetCheck(False, STATE_MISSING, "数据集表为空")
            root_path = row["root_path"] or osp.dirname(path)
            return DatasetCheck(
                True,
                STATE_ACTIVE,
                "",
                uuid=row["uuid"],
                name=row["name"],
                root_path=root_path,
                description=row["description"],
            )
        finally:
            database.close()

    # -- queries -----------------------------------------------------------
    def list(self, include_deleted: bool = False) -> list[RegistryEntry]:
        sql = "SELECT * FROM dataset_registry"
        if not include_deleted:
            sql += " WHERE state != ?"
        sql += " ORDER BY state, display_name COLLATE NOCASE, db_path"
        with self._connection() as connection:
            if include_deleted:
                rows = connection.execute(sql).fetchall()
            else:
                rows = connection.execute(sql, (STATE_DELETED,)).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get(self, uuid: str) -> RegistryEntry:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
        if row is None:
            raise RegistryEntryNotFoundError(uuid)
        return self._row_to_entry(row)

    def get_by_path(self, db_path: str) -> RegistryEntry | None:
        path = _normalize_path(db_path)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry "
                "WHERE db_path = ? COLLATE NOCASE",
                (path,),
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def events(self, uuid: str | None = None, limit: int = 200):
        sql = "SELECT * FROM dataset_registry_event"
        parameters: tuple = ()
        if uuid is not None:
            sql += " WHERE uuid = ?"
            parameters = (uuid,)
        sql += " ORDER BY id DESC LIMIT ?"
        parameters += (int(limit),)
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    # -- mutations ---------------------------------------------------------
    def add(
        self,
        uuid: str,
        db_path: str,
        display_name: str = "",
        root_path: str = "",
        operator_id: int | None = None,
    ) -> RegistryEntry:
        path = _normalize_path(db_path)
        name = (display_name or "").strip()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO dataset_registry "
                "(uuid, db_path, display_name, root_path, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(uuid) DO UPDATE SET "
                "db_path = excluded.db_path, "
                "display_name = excluded.display_name, "
                "root_path = excluded.root_path, "
                "state = 'active'",
                (
                    uuid,
                    path,
                    name,
                    _normalize_path(root_path) if root_path else "",
                    STATE_ACTIVE,
                    _now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
            registry_id = int(row["id"])
            self._log_event(
                connection,
                registry_id,
                uuid,
                "add",
                operator_id,
                {"db_path": path},
            )
        return self._row_to_entry(row)

    def add_from_folder(
        self, folder: str, display_name: str = "", operator_id: int | None = None
    ) -> RegistryEntry:
        db_path = osp.join(_normalize_path(folder), DATABASE_FILENAME)
        check = self.check_dataset(db_path)
        if not check.ok:
            raise RegistryError(check.reason or "not a dataset database")
        existing = self.get_by_path(db_path)
        if existing is not None:
            return existing
        return self.add(
            uuid=check.uuid,
            db_path=db_path,
            display_name=display_name or check.name,
            root_path=check.root,
            operator_id=operator_id,
        )

    def rename(
        self, uuid: str, name: str, operator_id: int | None = None
    ) -> RegistryEntry:
        value = (name or "").strip()
        if not value:
            raise RegistryError("数据集名称不能为空")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
            if row is None:
                raise RegistryEntryNotFoundError(uuid)
            connection.execute(
                "UPDATE dataset_registry SET display_name = ? WHERE uuid = ?",
                (value, uuid),
            )
            self._log_event(
                connection,
                int(row["id"]),
                uuid,
                "rename",
                operator_id,
                {"from": row["display_name"], "to": value},
            )
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
        return self._row_to_entry(row)

    def touch(
        self, uuid: str, operator_id: int | None = None
    ) -> RegistryEntry:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
            if row is None:
                raise RegistryEntryNotFoundError(uuid)
            connection.execute(
                "UPDATE dataset_registry SET last_opened_at = ?, "
                "last_opened_by = ?, state = ? WHERE uuid = ?",
                (_now(), operator_id, STATE_ACTIVE, uuid),
            )
            self._log_event(
                connection, int(row["id"]), uuid, "open", operator_id
            )
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
        return self._row_to_entry(row)

    def mark_missing(
        self, uuid: str, reason: str = "", operator_id: int | None = None
    ) -> None:
        self._set_state(
            uuid, STATE_MISSING, operator_id, "mark_missing", {"reason": reason}
        )

    def relocate(
        self,
        uuid: str,
        new_db_path: str,
        operator_id: int | None = None,
    ) -> RegistryEntry:
        path = _normalize_path(new_db_path)
        check = self.check_dataset(path)
        if not check.ok:
            raise RegistryError(check.reason or "not a dataset database")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
            if row is None:
                raise RegistryEntryNotFoundError(uuid)
            connection.execute(
                "UPDATE dataset_registry SET db_path = ?, root_path = ?, "
                "state = ? WHERE uuid = ?",
                (path, check.root, STATE_ACTIVE, uuid),
            )
            self._log_event(
                connection,
                int(row["id"]),
                uuid,
                "relocate",
                operator_id,
                {"from": row["db_path"], "to": path},
            )
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
        return self._row_to_entry(row)

    def mark_deleted(
        self,
        uuid: str,
        operator_id: int | None = None,
        delete_mode: str = "",
        backup_path: str = "",
    ) -> None:
        self._set_state(
            uuid,
            STATE_DELETED,
            operator_id,
            "delete",
            {"mode": delete_mode, "backup_path": backup_path},
            delete_mode=delete_mode,
            backup_path=backup_path,
        )

    def remove_record(
        self, uuid: str, operator_id: int | None = None
    ) -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
            if row is None:
                raise RegistryEntryNotFoundError(uuid)
            connection.execute(
                "DELETE FROM dataset_registry WHERE uuid = ?", (uuid,)
            )
            self._log_event(
                connection,
                None,
                uuid,
                "remove_record",
                operator_id,
                {"db_path": row["db_path"]},
            )

    def set_state(
        self,
        uuid: str,
        state: str,
        operator_id: int | None = None,
        action: str = "set_state",
    ) -> None:
        self._set_state(uuid, state, operator_id, action, {})

    # -- helpers -----------------------------------------------------------
    def _set_state(
        self,
        uuid: str,
        state: str,
        operator_id: int | None,
        action: str,
        detail: dict,
        delete_mode: str = "",
        backup_path: str = "",
    ) -> None:
        if state not in STATES:
            raise RegistryError(f"unknown registry state: {state}")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_registry WHERE uuid = ?", (uuid,)
            ).fetchone()
            if row is None:
                raise RegistryEntryNotFoundError(uuid)
            if state == STATE_DELETED:
                connection.execute(
                    "UPDATE dataset_registry SET state = ?, deleted_at = ?, "
                    "deleted_by = ?, delete_mode = ?, backup_path = ? "
                    "WHERE uuid = ?",
                    (
                        state,
                        _now(),
                        operator_id,
                        delete_mode,
                        backup_path,
                        uuid,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE dataset_registry SET state = ? WHERE uuid = ?",
                    (state, uuid),
                )
            self._log_event(
                connection, int(row["id"]), uuid, action, operator_id, detail
            )

    def _log_event(
        self,
        connection,
        registry_id: int | None,
        uuid: str,
        action: str,
        operator_id: int | None,
        detail: dict | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO dataset_registry_event "
            "(registry_id, uuid, action, operator_id, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                registry_id,
                uuid,
                action,
                operator_id,
                json.dumps(detail or {}, ensure_ascii=False),
                _now(),
            ),
        )

    @staticmethod
    def _row_to_entry(row) -> RegistryEntry:
        return RegistryEntry(
            id=int(row["id"]),
            uuid=row["uuid"],
            db_path=row["db_path"],
            display_name=row["display_name"],
            root_path=row["root_path"],
            state=row["state"],
            created_at=row["created_at"],
            last_opened_at=row["last_opened_at"],
            last_opened_by=row["last_opened_by"],
            deleted_at=row["deleted_at"],
            deleted_by=row["deleted_by"],
            delete_mode=row["delete_mode"],
            backup_path=row["backup_path"],
        )


def _application_id() -> int:
    from .schema import APPLICATION_ID

    return APPLICATION_ID
