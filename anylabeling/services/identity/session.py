"""Operator identity session and the service that ties store and session.

The application runs with one process-wide operator session: the menu bar,
the labeling windows and the auto-labeling worker must all agree on who is
currently logged in.  The session is intentionally explicit rather than a
hidden global - :func:`get_operator_service` is the single documented access
point and :func:`reset_operator_service` exists for tests.  Widgets accept an
optional service instance so unit tests never touch the real work directory.

Closing the application always ends the session: nothing about the login is
persisted, so the next launch starts in browse mode.
"""

from __future__ import annotations

import logging
import os
import os.path as osp
import shutil
import sys
import threading

from .store import Operator, OperatorStore

logger = logging.getLogger(__name__)

APP_DIRNAME = "X-AnyLabeling"
DEFAULT_IDENTITY_DIRNAME = "operators"
DEFAULT_DATABASE_FILENAME = "operators.db"
#: Legacy location: written below the configurable work directory until
#: fork.5, which made accounts disappear when ``--work-dir`` changed.
LEGACY_DATA_DIRNAME = "xanylabeling_data"


def _platform_data_directory() -> str:
    """Return a per-user application data directory independent of work_dir."""
    home = osp.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("APPDATA") or osp.join(
            home, "AppData", "Roaming"
        )
    elif sys.platform == "darwin":
        base = osp.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or osp.join(
            home, ".local", "share"
        )
    return osp.join(base, APP_DIRNAME)


def default_database_path() -> str:
    """Return the account database path (machine-scoped, not project-scoped).

    The operator accounts follow the application, not the dataset directory,
    so this path must not depend on ``--work-dir``.
    """
    return osp.join(
        _platform_data_directory(),
        DEFAULT_IDENTITY_DIRNAME,
        DEFAULT_DATABASE_FILENAME,
    )


def legacy_database_path(work_dir: str | None = None) -> str:
    """Return the pre-fork.5 account database location below ``work_dir``."""
    if work_dir is None:
        from anylabeling.config import get_work_directory

        work_dir = get_work_directory()
    return osp.join(
        work_dir,
        LEGACY_DATA_DIRNAME,
        DEFAULT_IDENTITY_DIRNAME,
        DEFAULT_DATABASE_FILENAME,
    )


def migrate_legacy_database(
    target_path: str | None = None, legacy_path: str | None = None
) -> bool:
    """Copy a pre-fork.5 account database to the stable location.

    The legacy file is copied, not moved: it is the only source of the
    account names and removing it is left to the user.
    """
    target = target_path or default_database_path()
    if osp.exists(target):
        return False
    legacy = (
        legacy_path if legacy_path is not None else legacy_database_path()
    )
    if not legacy or not osp.exists(legacy):
        return False
    directory = osp.dirname(target)
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        shutil.copy2(legacy, target)
    except OSError:
        logger.warning(
            "Could not migrate the operator database from %s", legacy
        )
        return False
    logger.info(
        "Migrated the operator database from %s to %s", legacy, target
    )
    return True


class OperatorSession:
    """Who is logged in right now.

    Listeners are plain callables invoked with the session as their only
    argument after every change.  They must not raise; failures are logged and
    ignored so one broken window cannot block a login.
    """

    def __init__(self):
        self._operator: Operator | None = None
        self._listeners: list = []
        self._lock = threading.RLock()

    @property
    def operator(self) -> Operator | None:
        return self._operator

    @property
    def is_logged_in(self) -> bool:
        return self._operator is not None

    @property
    def operator_name(self) -> str:
        return self._operator.name if self._operator is not None else ""

    def login(self, operator: Operator) -> None:
        if not isinstance(operator, Operator):
            raise TypeError("login() expects an Operator instance")
        with self._lock:
            self._operator = operator
        self._notify()

    def logout(self) -> None:
        with self._lock:
            changed = self._operator is not None
            self._operator = None
        if changed:
            self._notify()

    def subscribe(self, callback):
        """Register ``callback``; returns a function that unsubscribes it."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._listeners.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)

        return unsubscribe

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(self)
            except Exception:  # noqa: BLE001 - keep other listeners alive
                logger.exception("Operator session listener failed")


class OperatorService:
    """Account store plus the current session."""

    def __init__(self, db_path: str | None = None, *, store=None):
        self._db_path = db_path
        self._explicit_db_path = db_path is not None
        self._store = store
        self.session = OperatorSession()

    @property
    def db_path(self) -> str:
        if self._db_path is None:
            self._db_path = default_database_path()
        return self._db_path

    @property
    def store(self) -> OperatorStore:
        if self._store is None:
            target = self.db_path
            if not self._explicit_db_path:
                migrate_legacy_database(target)
            self._store = OperatorStore(target)
        return self._store

    # -- session convenience -------------------------------------------------
    def login(self, name: str, password: str) -> Operator:
        operator = self.store.authenticate(name, password)
        self.session.login(operator)
        return operator

    def register(self, name: str, password: str) -> Operator:
        """Register and immediately log the new operator in."""
        operator = self.store.register(name, password)
        self.session.login(operator)
        return operator

    def logout(self) -> None:
        self.session.logout()

    @property
    def current_operator_name(self) -> str:
        return self.session.operator_name


_service: OperatorService | None = None
_service_lock = threading.Lock()


def get_operator_service() -> OperatorService:
    """Return the process-wide operator service (created on first use)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = OperatorService()
    return _service


def reset_operator_service(service: OperatorService | None = None) -> None:
    """Replace the process-wide service; intended for tests."""
    global _service
    with _service_lock:
        _service = service
