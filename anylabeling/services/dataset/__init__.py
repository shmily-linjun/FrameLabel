"""SQLite dataset storage service (T3).

P0 exposes the database, codec, repository and XLABEL folder importer; the
GUI integration follows in later phases.  Nothing here imports Qt.
"""

from .annotation_import import (
    AnnotationImportResult,
    store_annotation,
    store_annotations,
)
from .codec import ImageAnnotation, parse_xlabel_data
from .connection import DATABASE_FILENAME, DatasetDatabase
from .errors import (
    DatasetConflictError,
    DatasetError,
    DatasetFormatError,
    DatasetNotFoundError,
)
from .importer import ImportReport, import_xlabel_folder
from .repository import DatasetRepository
from .schema import APPLICATION_ID, SCHEMA_SQL, SCHEMA_VERSION

__all__ = [
    "APPLICATION_ID",
    "AnnotationImportResult",
    "DATABASE_FILENAME",
    "DatasetConflictError",
    "DatasetDatabase",
    "DatasetError",
    "DatasetFormatError",
    "DatasetNotFoundError",
    "DatasetRepository",
    "ImageAnnotation",
    "ImportReport",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "import_xlabel_folder",
    "parse_xlabel_data",
    "store_annotation",
    "store_annotations",
]
