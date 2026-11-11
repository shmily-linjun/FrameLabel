"""Aggregate dataset statistics for the right-side "Statistics" tab.

This module is Qt-free: it only reads annotation JSON files and aggregates
counts into a table model that :mod:`...widgets.statistics_table` renders.
Keeping the logic here makes it testable without a ``QApplication``.

Counting rules
--------------
* A ``(class, split)`` cell counts *images*, i.e. how many images of that
  split contain the class at least once (a class used several times in one
  image counts once).  This matches what clicking the cell filters to.
* The ``(No objects)`` row counts images whose annotation contains no labelled
  object.  Images without an annotation JSON file count as objectless too,
  because the search engine treats a missing label file as "no objects".
* The ``Total`` column of a class row (and of the objectless row) is the sum of
  that row across splits, i.e. how many images contain the class / are
  objectless.
* The ``Total`` row counts *files* per split (an image with several classes is
  counted once), and the bottom-right ``Total`` cell is the total number of
  collected images -- it is not the sum of the class cells.  This mirrors the
  reference screenshot where the class cells may exceed the split file count.

The displayed order is fixed: ``Train / Val / Test / Unassigned / Total``.
"""

import json
import os
import os.path as osp
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .file_meta import (
    SPLIT_KEYS,
    SPLIT_NONE,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
)

# -- display order / display texts --------------------------------------

#: Split order used by the statistics table columns.
SPLIT_ORDER = (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST, SPLIT_NONE)

#: Statistics tab title, for label_widget (wrap it in ``self.tr()``).
#: English is the translation source; zh/ja/ko live in the .ts files.
STATISTICS_TAB_TITLE = "Statistics"

#: First column header ("class names").
CLASS_COLUMN_HEADER = "Class"

#: Split column headers, in :data:`SPLIT_ORDER` order.
SPLIT_COLUMN_HEADERS = {
    SPLIT_TRAIN: "Train",
    SPLIT_VAL: "Val",
    SPLIT_TEST: "Test",
    SPLIT_NONE: "Unassigned",
}

#: Totals column header.
TOTAL_COLUMN_HEADER = "Total"

#: Row label for images without any labelled object.
OBJECTLESS_ROW_LABEL = "(No objects)"

#: Row label for the totals row.
TOTAL_ROW_LABEL = "Total"

# -- column geometry -----------------------------------------------------

#: Column index of the class-name column.
COLUMN_CLASS = 0

#: Column indices of the split columns (in :data:`SPLIT_ORDER` order).
COLUMN_SPLITS = tuple(range(1, len(SPLIT_ORDER) + 1))

#: Column index of the totals column (not clickable).
COLUMN_TOTAL = len(SPLIT_ORDER) + 1

#: Number of columns of the table, including the class column.
COLUMN_COUNT = COLUMN_TOTAL + 1

#: All column headers, left to right.
COLUMN_HEADERS = (
    (CLASS_COLUMN_HEADER,)
    + tuple(SPLIT_COLUMN_HEADERS[split] for split in SPLIT_ORDER)
    + (TOTAL_COLUMN_HEADER,)
)

#: ``split_index`` sentinel used by :func:`filter_for_cell` for the totals
#: column, which is not clickable.
SPLIT_INDEX_TOTAL = len(SPLIT_ORDER)

# -- row kinds used by :func:`filter_for_cell` ---------------------------

ROW_KIND_CLASS = "class"
ROW_KIND_OBJECTLESS = "objectless"
ROW_KIND_TOTAL = "total"


@dataclass(frozen=True)
class StatisticsFilter:
    """Structured filter produced by clicking on the statistics table.

    Attributes:
        label: Class to filter by, or ``None`` for "any class".
        split: Canonical split key (``none``/``train``/``val``/``test``) or
            ``None`` for "any split".
        objectless: When true the filter targets images without objects.
    """

    label: Optional[str] = None
    split: Optional[str] = None
    objectless: bool = False


@dataclass(frozen=True)
class FileStatisticsEntry:
    """Per-image statistics read from one annotation file."""

    path: str
    split: str = SPLIT_NONE
    labels: Tuple[str, ...] = ()
    has_label_file: bool = False

    @property
    def is_objectless(self) -> bool:
        """Whether this image has no labelled object."""
        return not self.labels


@dataclass
class ClassSplitTable:
    """Aggregated class x split counts for the statistics table."""

    classes: Tuple[str, ...] = ()
    splits: Tuple[str, ...] = SPLIT_ORDER
    #: ``class -> split -> image count`` for every known class.
    counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    #: ``split -> objectless image count``.
    objectless_counts: Dict[str, int] = field(default_factory=dict)
    #: ``class -> total image count over all splits`` (totals column).
    class_totals: Dict[str, int] = field(default_factory=dict)
    #: ``split -> number of images in that split`` (totals row; an image with
    #: several classes is counted once).
    split_totals: Dict[str, int] = field(default_factory=dict)
    #: Total of the objectless row.
    objectless_total: int = 0
    #: Grand total (bottom-right cell): total number of collected images.
    total: int = 0
    #: Number of collected images.
    entry_count: int = 0

    @property
    def is_empty(self) -> bool:
        """Whether the table holds no class and no objectless image."""
        return not self.classes and self.total == 0

    def count_for(self, class_name: str, split: str) -> int:
        """Return the number of images with ``class_name`` in ``split``."""
        return self.counts.get(class_name, {}).get(split, 0)

    def objectless_for(self, split: str) -> int:
        """Return the number of objectless images in ``split``."""
        return self.objectless_counts.get(split, 0)

    def total_for_class(self, class_name: str) -> int:
        """Return the totals-column value of a class row."""
        return self.class_totals.get(class_name, 0)

    def total_for_split(self, split: str) -> int:
        """Return the totals-row value of a split column."""
        return self.split_totals.get(split, 0)


def normalize_split(value) -> str:
    """Normalize a raw ``split`` value to one of :data:`SPLIT_KEYS`."""
    if isinstance(value, str) and value in SPLIT_KEYS:
        return value
    return SPLIT_NONE


def image_label_file(image_path, output_dir=None) -> str:
    """Resolve the annotation JSON path of ``image_path``.

    Mirrors the rest of the application: without ``output_dir`` the JSON is
    next to the image with the same stem; with ``output_dir`` its basename is
    looked up inside ``output_dir``.
    """
    path = _to_text(image_path)
    if not path:
        return ""
    label_file = osp.splitext(path)[0] + ".json"
    if output_dir:
        output_dir = _to_text(output_dir)
        if output_dir:
            label_file = osp.join(output_dir, osp.basename(label_file))
    return label_file


def collect_entries(image_files, output_dir=None) -> List[FileStatisticsEntry]:
    """Read one :class:`FileStatisticsEntry` per image in ``image_files``.

    Missing, unreadable or malformed annotation files are not an error: the
    entry keeps ``split="none"``, an empty ``labels`` tuple and
    ``has_label_file=False`` (such an image is counted as objectless).
    The returned list preserves the input order.
    """
    entries: List[FileStatisticsEntry] = []
    for image_path in image_files or ():
        path = _to_text(image_path)
        if not path:
            continue
        label_file = image_label_file(path, output_dir)
        data = _load_annotation(label_file)
        if data is None:
            entries.append(
                FileStatisticsEntry(
                    path=path,
                    split=SPLIT_NONE,
                    labels=(),
                    has_label_file=False,
                )
            )
            continue
        entries.append(
            FileStatisticsEntry(
                path=path,
                split=normalize_split(data.get("split", SPLIT_NONE)),
                labels=_labels_from_annotation(data),
                has_label_file=True,
            )
        )
    return entries


def build_class_split_table(entries) -> ClassSplitTable:
    """Aggregate ``entries`` into a :class:`ClassSplitTable`.

    ``entries`` may be ``None`` or empty; the result is then an empty table
    (no classes, zeroed rows/columns) that the UI can still render.
    """
    split_counts: Dict[str, Dict[str, int]] = {}
    split_file_counts: Dict[str, int] = {split: 0 for split in SPLIT_ORDER}
    objectless_counts: Dict[str, int] = {split: 0 for split in SPLIT_ORDER}
    entry_count = 0

    for entry in entries or ():
        entry_count += 1
        split = normalize_split(getattr(entry, "split", SPLIT_NONE))
        split_file_counts[split] += 1
        labels = _clean_labels(getattr(entry, "labels", ()))
        if not labels:
            objectless_counts[split] += 1
            continue
        for label in labels:
            row = split_counts.setdefault(
                label, {split_key: 0 for split_key in SPLIT_ORDER}
            )
            row[split] += 1

    classes = tuple(sorted(split_counts))
    counts: Dict[str, Dict[str, int]] = {}
    class_totals: Dict[str, int] = {}
    for label in classes:
        row = dict(split_counts[label])
        counts[label] = row
        class_totals[label] = sum(row.values())

    return ClassSplitTable(
        classes=classes,
        splits=SPLIT_ORDER,
        counts=counts,
        objectless_counts=objectless_counts,
        class_totals=class_totals,
        split_totals=dict(split_file_counts),
        objectless_total=sum(objectless_counts.values()),
        total=entry_count,
        entry_count=entry_count,
    )


def filter_for_cell(
    table: ClassSplitTable,
    row_kind: str,
    class_index: Optional[int] = None,
    split_index: Optional[int] = None,
) -> Optional[StatisticsFilter]:
    """Build the filter for one data cell, or ``None`` if not clickable.

    Args:
        table: Aggregation the cell belongs to.
        row_kind: One of :data:`ROW_KIND_CLASS`, :data:`ROW_KIND_OBJECTLESS`
            or :data:`ROW_KIND_TOTAL`.
        class_index: Index into ``table.classes`` (class rows only).
        split_index: ``None`` for the class-name column, ``0 .. len(splits)-1``
            for a split column, :data:`SPLIT_INDEX_TOTAL` for the totals
            column (never clickable).

    Returns:
        A :class:`StatisticsFilter`, or ``None`` for the totals row and the
        totals column (which are deliberately not clickable).
    """
    if table is None or row_kind == ROW_KIND_TOTAL:
        return None
    if split_index is not None:
        if split_index == SPLIT_INDEX_TOTAL:
            return None
        if not 0 <= split_index < len(SPLIT_ORDER):
            return None
        split = SPLIT_ORDER[split_index]
    else:
        split = None

    if row_kind == ROW_KIND_CLASS:
        if class_index is None or not 0 <= class_index < len(table.classes):
            return None
        return StatisticsFilter(label=table.classes[class_index], split=split)
    if row_kind == ROW_KIND_OBJECTLESS:
        return StatisticsFilter(split=split, objectless=True)
    return None


# -- helpers -------------------------------------------------------------
def _labels_from_annotation(data: dict) -> Tuple[str, ...]:
    """Return the sorted, de-duplicated class labels of an annotation."""
    shapes = data.get("shapes") or ()
    if not isinstance(shapes, (list, tuple)):
        return ()
    labels = []
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        label = shape.get("label")
        if isinstance(label, str) and label:
            labels.append(label)
    return tuple(sorted(set(labels)))


def _clean_labels(labels) -> Tuple[str, ...]:
    """Normalize hand-built entry labels to a sorted, unique tuple."""
    if not labels:
        return ()
    cleaned = {
        label for label in labels if isinstance(label, str) and label
    }
    return tuple(sorted(cleaned))


def _load_annotation(path: str) -> Optional[dict]:
    """Load an annotation file, returning ``None`` when unusable."""
    path = _to_text(path)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _to_text(value) -> str:
    """Best-effort conversion of a path-like value to text."""
    if value is None:
        return ""
    try:
        path = os.fspath(value)
    except TypeError:
        path = value
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str):
        path = str(path)
    return path
