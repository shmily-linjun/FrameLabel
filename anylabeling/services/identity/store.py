"""SQLite storage for the local operator accounts.

The annotation data stays in the XLABEL JSON files; only the account
directory lives in this database.  That keeps the feature independent from
the planned project database migration while still giving the accounts a
durable, queryable home.

Every public method opens a short-lived connection.  The database is tiny and
writes are rare, so this is cheaper than sharing a connection between the
labeling windows and the worker threads.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import os.path as osp
import sqlite3
import threading
from dataclasses import dataclass

from . import passwords

SCHEMA_VERSION = "1"
MAX_NAME_LENGTH = 64

#: Names that must never be registered because they are reserved sentinels in
#: the annotation data (see :mod:`anylabeling.services.identity.attribution`).
RESERVED_NAMES = frozenset({"none"})


class OperatorError(Exception):
    """Base class for operator storage errors."""


class OperatorNameError(OperatorError, ValueError):
    """Raised for an empty, oversized or malformed operator name."""


class OperatorExistsError(OperatorError):
    """Raised when a name is already registered (case-insensitive)."""


class ReservedOperatorNameError(OperatorError):
    """Raised when trying to register a reserved name such as ``none``."""


class OperatorCredentialsError(OperatorError):
    """Raised when a name/password pair does not authenticate."""


class OperatorDisabledError(OperatorError):
    """Raised when the account exists but has been disabled."""


class OperatorPermissionError(OperatorError):
    """Raised when a non-admin account tries to manage other accounts."""


class OperatorStorageError(OperatorError):
    """Raised when the database file cannot be opened or written."""


@dataclass(frozen=True)
class Operator:
    """One registered operator account."""

    id: int
    name: str
    is_admin: bool
    disabled: bool = False


def _now_timestamp() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_name(name: object) -> tuple[str, str]:
    """Validate a display name and return ``(display_name, lookup_key)``."""
    if not isinstance(name, str):
        raise OperatorNameError("Operator name must be a string.")
    display = name.strip()
    if not display:
        raise OperatorNameError("Operator name must not be empty.")
    if len(display) > MAX_NAME_LENGTH:
        raise OperatorNameError(
            f"Operator name must be at most {MAX_NAME_LENGTH} characters."
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in display):
        raise OperatorNameError(
            "Operator name must not contain control characters."
        )
    key = display.casefold()
    if key in RESERVED_NAMES:
        raise ReservedOperatorNameError(
            f"'{display}' is reserved and cannot be registered."
        )
    return display, key


class OperatorStore:
    """Read/write access to the operator SQLite database."""

    def __init__(self, db_path: str):
        if not db_path:
            raise OperatorStorageError("Operator database path is empty.")
        self.db_path = osp.abspath(osp.expanduser(db_path))
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    # -- connection handling -------------------------------------------------
    @contextlib.contextmanager
    def _connection(self):
        directory = osp.dirname(self.db_path)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            connection = sqlite3.connect(self.db_path, timeout=5.0)
        except (OSError, sqlite3.Error) as error:
            raise OperatorStorageError(
                f"Cannot open the operator database '{self.db_path}': {error}"
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
            raise OperatorStorageError(
                f"Operator database error: {error}"
            ) from error
        finally:
            connection.close()

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            connection.execute(
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
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )
            connection.commit()
            self._schema_ready = True

    # -- queries -------------------------------------------------------------
    @staticmethod
    def _row_to_operator(row: sqlite3.Row) -> Operator:
        return Operator(
            id=int(row["id"]),
            name=str(row["name"]),
            is_admin=bool(row["is_admin"]),
            disabled=bool(row["disabled"]),
        )

    def _fetch_by_key(self, connection, name_key: str):
        return connection.execute(
            "SELECT * FROM operator WHERE name_key = ?", (name_key,)
        ).fetchone()

    def count(self) -> int:
        """Return the number of registered accounts (including disabled)."""
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM operator")
            return int(row.fetchone()["total"])

    def list_operators(self) -> list[Operator]:
        """Return all accounts ordered by their case-insensitive key."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM operator ORDER BY name_key"
            ).fetchall()
        return [self._row_to_operator(row) for row in rows]

    def get(self, name: str) -> Operator | None:
        """Return the account with ``name`` (case-insensitive) or ``None``."""
        try:
            _display, key = normalize_name(name)
        except OperatorNameError:
            return None
        with self._connection() as connection:
            row = self._fetch_by_key(connection, key)
        return self._row_to_operator(row) if row else None

    def has_name(self, name: str) -> bool:
        return self.get(name) is not None

    # -- mutations -----------------------------------------------------------
    def register(self, name: str, password: str) -> Operator:
        """Create an account.  The very first account becomes the admin."""
        display, key = normalize_name(name)
        passwords.validate_password(password)
        hash_hex, salt_hex, iterations = passwords.hash_password(password)
        with self._connection() as connection:
            if self._fetch_by_key(connection, key) is not None:
                raise OperatorExistsError(
                    f"Operator '{display}' already exists."
                )
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS total FROM operator"
                ).fetchone()["total"]
            )
            is_admin = 1 if total == 0 else 0
            cursor = connection.execute(
                """
                INSERT INTO operator (
                    name, name_key, password_hash, password_salt,
                    password_iterations, is_admin, disabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    display,
                    key,
                    hash_hex,
                    salt_hex,
                    iterations,
                    is_admin,
                    _now_timestamp(),
                ),
            )
            return Operator(
                id=int(cursor.lastrowid),
                name=display,
                is_admin=bool(is_admin),
            )

    def authenticate(self, name: str, password: str) -> Operator:
        """Return the account when ``name``/``password`` match."""
        try:
            _display, key = normalize_name(name)
        except OperatorNameError as error:
            raise OperatorCredentialsError(str(error)) from error
        with self._connection() as connection:
            row = self._fetch_by_key(connection, key)
            if row is None:
                passwords.verify_password(
                    password, "00", "00", passwords.PBKDF2_ITERATIONS
                )
                raise OperatorCredentialsError(
                    "Unknown operator or wrong password."
                )
            if not passwords.verify_password(
                password,
                row["password_hash"],
                row["password_salt"],
                int(row["password_iterations"]),
            ):
                raise OperatorCredentialsError(
                    "Unknown operator or wrong password."
                )
            operator = self._row_to_operator(row)
        if operator.disabled:
            raise OperatorDisabledError(
                f"Operator '{operator.name}' is disabled."
            )
        return operator

    def change_password(
        self,
        target_name: str,
        new_password: str,
        *,
        admin_name: str,
        admin_password: str,
    ) -> None:
        """Reset ``target_name``'s password after checking an admin account."""
        admin = self.authenticate(admin_name, admin_password)
        if not admin.is_admin:
            raise OperatorPermissionError(
                f"Operator '{admin.name}' is not an administrator."
            )
        try:
            _display, key = normalize_name(target_name)
        except OperatorNameError as error:
            raise OperatorStorageError(str(error)) from error
        hash_hex, salt_hex, iterations = passwords.hash_password(new_password)
        with self._connection() as connection:
            row = self._fetch_by_key(connection, key)
            if row is None:
                raise OperatorStorageError(
                    f"Operator '{target_name}' does not exist."
                )
            connection.execute(
                """
                UPDATE operator
                   SET password_hash = ?, password_salt = ?,
                       password_iterations = ?
                 WHERE name_key = ?
                """,
                (hash_hex, salt_hex, iterations, key),
            )

    def set_disabled(
        self,
        target_name: str,
        disabled: bool,
        *,
        admin_name: str,
        admin_password: str,
    ) -> None:
        """Disable or re-enable an account after checking an admin account."""
        admin = self.authenticate(admin_name, admin_password)
        if not admin.is_admin:
            raise OperatorPermissionError(
                f"Operator '{admin.name}' is not an administrator."
            )
        try:
            _display, key = normalize_name(target_name)
        except OperatorNameError as error:
            raise OperatorStorageError(str(error)) from error
        with self._connection() as connection:
            row = self._fetch_by_key(connection, key)
            if row is None:
                raise OperatorStorageError(
                    f"Operator '{target_name}' does not exist."
                )
            connection.execute(
                "UPDATE operator SET disabled = ? WHERE name_key = ?",
                (1 if disabled else 0, key),
            )
