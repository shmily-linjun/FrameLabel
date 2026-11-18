"""Local operator accounts and annotation attribution.

This package provides the offline identity layer of the fork:

* :mod:`passwords` - PBKDF2 hashing helpers (standard library only);
* :mod:`store` - the SQLite account directory;
* :mod:`session` - the process-wide operator session and service accessor;
* :mod:`attribution` - the ``author`` / ``modified_at`` JSON contract.

The account database is not the annotation storage.  XLABEL JSON files stay
authoritative for annotation content and carry their own ``author`` key.
"""

from .attribution import (
    AUTHOR_FIELD,
    AUTHOR_NONE,
    MODIFIED_AT_FIELD,
    content_signature,
    ensure_attribution,
    format_display_time,
    normalize_author,
    read_attribution,
    stamp_attribution,
)
from .session import (
    OperatorService,
    OperatorSession,
    default_database_path,
    get_operator_service,
    legacy_database_path,
    migrate_legacy_database,
    reset_operator_service,
)
from .store import (
    Operator,
    OperatorCredentialsError,
    OperatorDisabledError,
    OperatorError,
    OperatorExistsError,
    OperatorNameError,
    OperatorPermissionError,
    OperatorStorageError,
    OperatorStore,
    ReservedOperatorNameError,
)

__all__ = [
    "AUTHOR_FIELD",
    "AUTHOR_NONE",
    "MODIFIED_AT_FIELD",
    "Operator",
    "OperatorCredentialsError",
    "OperatorDisabledError",
    "OperatorError",
    "OperatorExistsError",
    "OperatorNameError",
    "OperatorPermissionError",
    "OperatorService",
    "OperatorSession",
    "OperatorStorageError",
    "OperatorStore",
    "ReservedOperatorNameError",
    "content_signature",
    "default_database_path",
    "ensure_attribution",
    "format_display_time",
    "get_operator_service",
    "legacy_database_path",
    "migrate_legacy_database",
    "normalize_author",
    "read_attribution",
    "reset_operator_service",
    "stamp_attribution",
]
