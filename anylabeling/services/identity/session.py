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
import os.path as osp
import threading

from .store import Operator, OperatorStore

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIRNAME = "xanylabeling_data"
DEFAULT_IDENTITY_DIRNAME = "operators"
DEFAULT_DATABASE_FILENAME = "operators.db"


def default_database_path() -> str:
    """Return the account database path inside the work directory."""
    from anylabeling.config import get_work_directory

    return osp.join(
        get_work_directory(),
        DEFAULT_DATA_DIRNAME,
        DEFAULT_IDENTITY_DIRNAME,
        DEFAULT_DATABASE_FILENAME,
    )


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
            self._store = OperatorStore(self.db_path)
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
