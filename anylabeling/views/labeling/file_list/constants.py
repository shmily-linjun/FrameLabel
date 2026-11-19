"""Column layout, colors and item roles of the labeling file table.

These values describe the six-column file table only.  Keeping them in a
small module lets the table widget, the controller and the labeling widget
share one source of truth without importing the (very large) main widget.
"""

from PyQt6.QtCore import Qt

FILE_CHECKED_COLOR = "#22A06B"
FILE_FAILED_COLOR = "#DE350B"
FILE_UNCHECKED_COLOR = "#8C98A4"

FILE_COL_NAME = 0
FILE_COL_SHAPES = 1
FILE_COL_IMPORT_TIME = 2
FILE_COL_INFERENCE = 3
FILE_COL_SPLIT = 4
FILE_COL_TAGS = 5
FILE_COLUMN_COUNT = 6
FILE_COL_NAME_WIDTH = 200
FILE_COL_NAME_MIN_WIDTH = 120
FILE_COLUMN_WIDTHS = {
    FILE_COL_SHAPES: 52,
    FILE_COL_IMPORT_TIME: 128,
    FILE_COL_INFERENCE: 64,
    FILE_COL_SPLIT: 56,
    FILE_COL_TAGS: 96,
}

FILE_ROW_HEIGHT = 36
FILE_ROW_HEIGHT_COMPACT = 20

FILE_PATH_ROLE = Qt.ItemDataRole.UserRole + 2
FILE_SORT_ROLE = Qt.ItemDataRole.UserRole + 1
