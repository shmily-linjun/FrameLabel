"""Statistics table widget for the right-side "Statistics" tab.

Renders the aggregation produced by
:mod:`anylabeling.views.labeling.utils.dataset_statistics`:

* first row: ``Class / Train / Val / Test / Unassigned / Total`` headers;
* one row per class, then the ``(No objects)`` row, then the ``Total`` row.

The table is read-only.  Clicking a cell emits :attr:`filter_requested` with
a :class:`~...dataset_statistics.StatisticsFilter` payload; the totals row and
the totals column are not clickable.  ``label_widget`` is expected to turn the
payload into a search query.
"""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ..utils.dataset_statistics import (
    COLUMN_CLASS,
    COLUMN_COUNT,
    COLUMN_HEADERS,
    COLUMN_SPLITS,
    COLUMN_TOTAL,
    OBJECTLESS_ROW_LABEL,
    ROW_KIND_CLASS,
    ROW_KIND_OBJECTLESS,
    ROW_KIND_TOTAL,
    SPLIT_INDEX_TOTAL,
    SPLIT_ORDER,
    STATISTICS_TAB_TITLE,
    TOTAL_ROW_LABEL,
    ClassSplitTable,
    StatisticsFilter,
    build_class_split_table,
    collect_entries,
    filter_for_cell,
)
from ..utils.style import get_file_table_style, get_scrollbar_style
from ..utils.theme import get_theme

#: Object name used by the per-widget stylesheet.
TABLE_OBJECT_NAME = "StatisticsTable"


class StatisticsTable(QtWidgets.QTableWidget):
    """Read-only class x split statistics table.

    Emits :attr:`filter_requested` when the user clicks a clickable cell or a
    split column header.
    """

    #: Tab title label_widget should use for the statistics page.
    TAB_TITLE = STATISTICS_TAB_TITLE

    #: Payload: :class:`StatisticsFilter` describing the clicked cell/header.
    filter_requested = QtCore.pyqtSignal(StatisticsFilter)

    def __init__(self, parent=None, entries=None):
        super().__init__(parent)
        self._statistics = build_class_split_table(())
        self._setup_widget()
        self.apply_theme()
        # Render the empty objectless/totals rows so the widget is usable
        # before the first refresh().
        self._populate(self._statistics)
        if entries is not None:
            self.set_entries(entries)

    # -- public API ----------------------------------------------------
    @property
    def statistics(self) -> ClassSplitTable:
        """The aggregation currently displayed."""
        return self._statistics

    def set_entries(self, entries) -> ClassSplitTable:
        """Build the table from :class:`FileStatisticsEntry` items."""
        table = build_class_split_table(entries)
        self.set_statistics(table)
        return table

    def set_statistics(self, table: ClassSplitTable) -> ClassSplitTable:
        """Display a pre-built :class:`ClassSplitTable`."""
        self._statistics = table or build_class_split_table(())
        self._populate(self._statistics)
        return self._statistics

    def refresh(self, image_files, output_dir=None) -> ClassSplitTable:
        """Re-read ``image_files`` annotations and rebuild the table."""
        return self.set_entries(collect_entries(image_files, output_dir))

    def cell_filter(self, row: int, column: int):
        """Return the :class:`StatisticsFilter` of a data cell or ``None``."""
        row_kind, class_index = self._row_info(row)
        if row_kind is None:
            return None
        if column < 0 or column >= COLUMN_COUNT:
            return None
        if column == COLUMN_CLASS:
            split_index = None
        elif column == COLUMN_TOTAL:
            split_index = SPLIT_INDEX_TOTAL
        else:
            split_index = column - 1
        return filter_for_cell(
            self._statistics,
            row_kind,
            class_index=class_index,
            split_index=split_index,
        )

    def header_filter(self, section: int):
        """Return the :class:`StatisticsFilter` of a header section or None."""
        if section not in COLUMN_SPLITS:
            return None
        return StatisticsFilter(split=SPLIT_ORDER[section - COLUMN_SPLITS[0]])

    def apply_theme(self) -> None:
        """Re-apply the theme-aware stylesheet and item decoration."""
        self.setStyleSheet(_statistics_table_style())
        self._restyle_items()

    # -- Qt setup ------------------------------------------------------
    def _setup_widget(self) -> None:
        self.setObjectName(TABLE_OBJECT_NAME)
        self.setAccessibleName(self.tr(STATISTICS_TAB_TITLE))
        self.setColumnCount(COLUMN_COUNT)
        self.setHorizontalHeaderLabels(
            [self.tr(header) for header in COLUMN_HEADERS]
        )
        self.setRowCount(2)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.verticalHeader().setDefaultSectionSize(24)

        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            COLUMN_CLASS, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        for column in COLUMN_SPLITS + (COLUMN_TOTAL,):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
        header.setSectionsClickable(True)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(40)

        self.cellClicked.connect(self._on_cell_clicked)
        header.sectionClicked.connect(self._on_header_clicked)

    # -- population ----------------------------------------------------
    def _populate(self, table: ClassSplitTable) -> None:
        class_count = len(table.classes)
        self.blockSignals(True)
        try:
            self.clearContents()
            self.setRowCount(class_count + 2)
            self.setColumnCount(COLUMN_COUNT)
            self.setHorizontalHeaderLabels(
                [self.tr(header) for header in COLUMN_HEADERS]
            )
            for row, label in enumerate(table.classes):
                self.setItem(
                    row,
                    COLUMN_CLASS,
                    self._make_item(label, self._name_alignment),
                )
                for offset, split in enumerate(SPLIT_ORDER):
                    self.setItem(
                        row,
                        COLUMN_SPLITS[offset],
                        self._make_item(table.count_for(label, split)),
                    )
                self.setItem(
                    row,
                    COLUMN_TOTAL,
                    self._make_item(table.total_for_class(label)),
                )

            objectless_row = class_count
            self.setItem(
                objectless_row,
                COLUMN_CLASS,
                self._make_item(
                    self.tr(OBJECTLESS_ROW_LABEL), self._name_alignment
                ),
            )
            for offset, split in enumerate(SPLIT_ORDER):
                self.setItem(
                    objectless_row,
                    COLUMN_SPLITS[offset],
                    self._make_item(table.objectless_for(split)),
                )
            self.setItem(
                objectless_row,
                COLUMN_TOTAL,
                self._make_item(table.objectless_total),
            )

            total_row = class_count + 1
            self.setItem(
                total_row,
                COLUMN_CLASS,
                self._make_item(
                    self.tr(TOTAL_ROW_LABEL), self._name_alignment
                ),
            )
            for offset, split in enumerate(SPLIT_ORDER):
                self.setItem(
                    total_row,
                    COLUMN_SPLITS[offset],
                    self._make_item(table.total_for_split(split)),
                )
            self.setItem(
                total_row, COLUMN_TOTAL, self._make_item(table.total)
            )
        finally:
            self.blockSignals(False)
        self._restyle_items()

    def _restyle_items(self) -> None:
        """Style the header-like first column and the totals row."""
        theme = get_theme()
        surface = QtGui.QBrush(QtGui.QColor(theme["surface"]))
        name_font = QtGui.QFont(self.font())
        name_font.setBold(True)
        total_font = QtGui.QFont(self.font())
        total_font.setBold(True)
        class_count = len(self._statistics.classes)
        total_row = class_count + 1
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if item is None:
                    continue
                if row == total_row:
                    item.setFont(total_font)
                    item.setBackground(surface)
                elif column == COLUMN_CLASS:
                    item.setFont(name_font)
                    item.setBackground(surface)
                else:
                    item.setFont(self.font())
                    item.setBackground(QtGui.QBrush())

    @property
    def _name_alignment(self):
        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    @staticmethod
    def _make_item(text, alignment=Qt.AlignmentFlag.AlignCenter):
        item = QtWidgets.QTableWidgetItem(str(text))
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        )
        item.setTextAlignment(alignment)
        return item

    # -- click handling ------------------------------------------------
    def _row_info(self, row: int):
        class_count = len(self._statistics.classes)
        if row < 0 or row > class_count + 1:
            return None, None
        if row < class_count:
            return ROW_KIND_CLASS, row
        if row == class_count:
            return ROW_KIND_OBJECTLESS, None
        return ROW_KIND_TOTAL, None

    def _on_cell_clicked(self, row: int, column: int) -> None:
        statistics_filter = self.cell_filter(row, column)
        if statistics_filter is not None:
            self.filter_requested.emit(statistics_filter)

    def _on_header_clicked(self, section: int) -> None:
        statistics_filter = self.header_filter(section)
        if statistics_filter is not None:
            self.filter_requested.emit(statistics_filter)


def _statistics_table_style() -> str:
    """Reuse the file table style with statistics-table specific tweaks."""
    theme = get_theme()
    base = get_file_table_style().replace(
        "QTableWidget#FileList", "QTableWidget#StatisticsTable"
    )
    return base + f"""
        QTableWidget#StatisticsTable {{
            gridline-color: {theme["border"]};
        }}
        QTableWidget#StatisticsTable::item {{
            padding: 2px 6px;
        }}
        QTableWidget#StatisticsTable QHeaderView::section:hover {{
            background-color: {theme["surface_hover"]};
            color: {theme["text"]};
        }}
        {get_scrollbar_style()}
    """
