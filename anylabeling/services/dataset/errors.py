"""Errors raised by the dataset database service."""


class DatasetError(Exception):
    """Base class for dataset database failures."""


class DatasetFormatError(DatasetError):
    """Raised when an annotation payload cannot be represented in the schema."""


class DatasetConflictError(DatasetError):
    """Raised when a write would violate a dataset invariant."""


class DatasetNotFoundError(DatasetError):
    """Raised when a dataset/database/row is missing."""
