"""Window control buttons drawn by the module (no icon resources needed)."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from .theme import FramelessTheme

KIND_MINIMIZE = "minimize"
KIND_MAXIMIZE = "maximize"
KIND_RESTORE = "restore"
KIND_CLOSE = "close"


class WindowButton(QtWidgets.QToolButton):
    """A minimize/maximize/restore/close button with a vector glyph."""

    def __init__(self, kind: str, theme: FramelessTheme, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._theme = theme
        self._hovered = False
        self._pressed = False
        self.setObjectName(
            "FramelessCloseButton"
            if kind == KIND_CLOSE
            else "FramelessWindowButton"
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setAutoRaise(True)
        self.setFixedSize(
            theme.window_button_width, theme.title_height
        )
        self.setToolTip(
            {
                KIND_MINIMIZE: self.tr("Minimize"),
                KIND_MAXIMIZE: self.tr("Maximize"),
                KIND_RESTORE: self.tr("Restore"),
                KIND_CLOSE: self.tr("Close"),
            }.get(kind, "")
        )

    # -- state ---------------------------------------------------------------
    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        if kind == self._kind:
            return
        self._kind = kind
        self.setToolTip(
            {
                KIND_MINIMIZE: self.tr("Minimize"),
                KIND_MAXIMIZE: self.tr("Maximize"),
                KIND_RESTORE: self.tr("Restore"),
                KIND_CLOSE: self.tr("Close"),
            }.get(kind, "")
        )
        self.update()

    def set_theme(self, theme: FramelessTheme) -> None:
        self._theme = theme
        self.setFixedSize(theme.window_button_width, theme.title_height)
        self.update()

    # -- painting ------------------------------------------------------------
    def _glyph_color(self) -> str:
        if self._kind == KIND_CLOSE and (self._hovered or self._pressed):
            return "#ffffff"
        return self._theme.button_text

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(self._glyph_color()))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        center = QtCore.QPointF(self.rect().center()) + QtCore.QPointF(
            0.5, 0.5
        )
        size = 5.0
        if self._kind == KIND_MINIMIZE:
            painter.drawLine(
                QtCore.QPointF(center.x() - size, center.y()),
                QtCore.QPointF(center.x() + size, center.y()),
            )
        elif self._kind == KIND_MAXIMIZE:
            painter.drawRect(
                QtCore.QRectF(
                    center.x() - size,
                    center.y() - size,
                    size * 2,
                    size * 2,
                )
            )
        elif self._kind == KIND_RESTORE:
            offset = 2.0
            painter.drawRect(
                QtCore.QRectF(
                    center.x() - size + offset,
                    center.y() - size - offset,
                    size * 2,
                    size * 2,
                )
            )
            painter.drawRect(
                QtCore.QRectF(
                    center.x() - size - offset,
                    center.y() - size + offset,
                    size * 2,
                    size * 2,
                )
            )
        elif self._kind == KIND_CLOSE:
            painter.drawLine(
                QtCore.QPointF(center.x() - size, center.y() - size),
                QtCore.QPointF(center.x() + size, center.y() + size),
            )
            painter.drawLine(
                QtCore.QPointF(center.x() + size, center.y() - size),
                QtCore.QPointF(center.x() - size, center.y() + size),
            )

    # -- hover ---------------------------------------------------------------
    def enterEvent(self, event):  # noqa: N802 - Qt naming
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt naming
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)
