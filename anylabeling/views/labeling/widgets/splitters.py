"""Custom splitters used by the labeling window chrome.

The handles are painted as a column/row of three dots so the draggable areas
read as separators in both light and dark themes.
"""

from PyQt6 import QtCore, QtGui, QtWidgets

from ..utils.theme import get_theme


class SidebarSplitterHandle(QtWidgets.QSplitterHandle):
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(get_theme()["text_secondary"]))
        center = QtCore.QPointF(self.width() / 2, self.height() / 2)
        for offset in (-5, 0, 5):
            painter.drawEllipse(center + QtCore.QPointF(0, offset), 1, 1)


class SidebarSplitter(QtWidgets.QSplitter):
    def createHandle(self):
        return SidebarSplitterHandle(self.orientation(), self)


class RightSplitterHandle(SidebarSplitterHandle):
    """Splitter handle between the right tab panel and the file table."""

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(get_theme()["text_secondary"]))
        center = QtCore.QPointF(self.width() / 2, self.height() / 2)
        for offset in (-5, 0, 5):
            painter.drawEllipse(center + QtCore.QPointF(offset, 0), 1, 1)


class RightSplitter(QtWidgets.QSplitter):
    def createHandle(self):
        return RightSplitterHandle(self.orientation(), self)
