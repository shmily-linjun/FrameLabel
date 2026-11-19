"""Qt controls used by the labeling file list.

The table keeps a small ``QListWidget``-compatible surface (``count``, a
single-argument ``item``, ``selectedItems``, ``currentItem``) because the rest
of the code base historically consumed a list widget.
"""

import os.path as osp

from PyQt6 import QtCore, QtGui, QtWidgets

from .constants import (
    FILE_COL_NAME,
    FILE_COL_NAME_MIN_WIDTH,
    FILE_SORT_ROLE,
)


def create_file_status_icon(color, filled=True):
    """Build the small circle icon that encodes an annotation check state."""
    pixmap = QtGui.QPixmap(10, 12)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    if filled:
        painter.setBrush(QtGui.QColor(color))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
    else:
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 1.5))
    painter.drawEllipse(1, 2, 8, 8)
    painter.end()
    return QtGui.QIcon(pixmap)


class FileNameDelegate(QtWidgets.QStyledItemDelegate):
    """Paint the file name column without the legacy per-row checkbox."""

    def displayText(self, value, locale):
        return osp.basename(super().displayText(value, locale))

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # The legacy file list encoded "has annotation file" in the check
        # state of each item. The table keeps that state for compatibility but
        # must not paint a per-row checkbox any more.
        option.features &= (
            ~QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        option.checkState = QtCore.Qt.CheckState.Unchecked

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(QtGui.QFontMetrics(option.font).height() + 4)
        return size


class FileTableItem(QtWidgets.QTableWidgetItem):
    """``QTableWidgetItem`` that carries a comparable sort key per cell."""

    def __init__(self, text="", sort_key=None):
        super().__init__(text)
        self.setData(FILE_SORT_ROLE, sort_key)


class FileTableWidget(QtWidgets.QTableWidget):
    """Five-column table listing the labeled images of the current folder."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._auto_fill_name_column = True
        self._adjusting_columns = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fill_name_column()

    def fill_name_column(self):
        """Let the file column take the remaining width when it is auto-sized."""
        if not self._auto_fill_name_column or self.columnCount() < 2:
            return
        header = self.horizontalHeader()
        if header is None:
            return
        used = sum(
            self.columnWidth(column)
            for column in range(1, self.columnCount())
            if not self.isColumnHidden(column)
        )
        width = max(FILE_COL_NAME_MIN_WIDTH, self.viewport().width() - used)
        if width == self.columnWidth(FILE_COL_NAME):
            return
        self._adjusting_columns = True
        try:
            self.setColumnWidth(FILE_COL_NAME, width)
        finally:
            self._adjusting_columns = False

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def count(self):
        return self.rowCount()

    def setCurrentRow(self, row):
        self.setCurrentCell(row, FILE_COL_NAME)

    def item(self, row, column=0):
        return super().item(row, column)

    def selected_rows(self):
        selection_model = self.selectionModel()
        if selection_model is None:
            return []
        return [index.row() for index in selection_model.selectedRows()]

    def selectedItems(self):
        items = []
        for row in self.selected_rows():
            item = self.item(row)
            if item is not None:
                items.append(item)
        return items

    def currentItem(self):
        row = self.currentRow()
        if row < 0:
            return None
        return self.item(row)
