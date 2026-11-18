"""Defines toolbar for anylabeling, including"""

from PyQt6 import QtCore, QtGui, QtWidgets
from anylabeling.views.labeling.utils.theme import get_theme


class ToolBarScrollArea(QtWidgets.QScrollArea):
    """Scrollable viewport hosting a complete ``QToolBar``.

    Qt only exposes hidden toolbar items through its extension button. The
    application requires the whole toolbar to be reachable with one
    scrollbar: vertical when docked left and horizontal when docked at the
    top. The wheel is forwarded to whichever scrollbar is active.
    """

    def wheelEvent(self, event):
        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        if (
            self.horizontalScrollBarPolicy()
            == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            and vertical.maximum() > 0
        ):
            delta = event.angleDelta().y() or event.angleDelta().x()
            vertical.setValue(vertical.value() - delta)
            event.accept()
            return
        if (
            self.verticalScrollBarPolicy()
            == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            and horizontal.maximum() > 0
        ):
            delta = event.angleDelta().y() or event.angleDelta().x()
            horizontal.setValue(horizontal.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)

    def sizeHint(self):  # noqa: N802 - Qt naming
        """Size the dock to the toolbar, not to the whole tool list.

        The scroll area's widget keeps its full natural size (that is what
        makes the toolbar scrollable), but the dock itself must only take the
        toolbar's width when docked left and its height when docked at the
        top.  Otherwise the top dock would ask for the full toolbar width and
        the left dock for the full toolbar height.
        """
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        hint = widget.sizeHint().expandedTo(widget.minimumSizeHint())
        vertical_mode = (
            self.verticalScrollBarPolicy()
            == QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        extent = self.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_ScrollBarExtent,
            None,
            self,
        )
        # A small allowance keeps the widget clear of the scrollbar when the
        # toolbar's reported hint is a few pixels smaller than its laid-out
        # size (QToolBar includes style padding at layout time).
        if vertical_mode:
            width = hint.width() + extent + 4
            return QtCore.QSize(width, 200)
        height = hint.height() + extent + 4
        return QtCore.QSize(200, height)

    def minimumSizeHint(self):  # noqa: N802 - Qt naming
        return self.sizeHint()


class ToolBar(QtWidgets.QToolBar):
    """Labeling tool bar hosted inside a scrollable dock pane.

    The bar itself is a real ``QToolBar``; ``MainWindow`` places it inside
    :class:`ToolBarScrollArea` in a ``QDockWidget`` so the complete tool set is
    reachable through a scrollbar. Floating is intentionally disabled: Qt 6's
    floating-toolbar path mis-sizes the floating window on Windows
    (``QWindowsWindow::setGeometry`` warnings with huge geometry), which made
    the toolbar unusable once detached.
    """

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setObjectName(f"{title}ToolBar")
        self.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setMovable(True)
        self.setFloatable(False)
        self.setAllowedAreas(
            QtCore.Qt.ToolBarArea.TopToolBarArea
            | QtCore.Qt.ToolBarArea.LeftToolBarArea
        )
        self._icon_size = 18
        self._button_size = 26
        self._label_mode = True
        self.setIconSize(
            QtCore.QSize(self._icon_size, self._icon_size),
        )
        self._apply_style()

    def set_label_mode(self, enabled):
        self._label_mode = bool(enabled)
        self.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            if self._label_mode
            else QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self._apply_style()

    def _apply_style(self):
        t = get_theme()
        min_width = self._button_size + (44 if self._label_mode else 0)
        min_height = self._button_size + (20 if self._label_mode else 0)
        self.setStyleSheet(f"""
            QToolBar {{
                background: transparent;
                border: none;
                spacing: 2px;
                padding: 0px;
                margin: 0px;
            }}
            QToolBar QToolButton {{
                border: none;
                background: transparent;
                padding: 2px 4px;
                margin: 0px;
                min-width: {min_width}px;
                min-height: {min_height}px;
            }}
            QToolBar QToolButton:hover {{
                border: 1px solid {t["border_light"]};
                border-radius: 6px;
                background: {t["surface_hover"]};
            }}
            QToolBar QToolButton:checked {{
                background: {t["surface_pressed"]};
                border-radius: 6px;
            }}
            QToolBar QToolButton#fitWindow:checked:!hover:!pressed {{
                background: transparent;
            }}
            QToolBar QToolButton:pressed {{
                background: {t["surface_pressed"]};
            }}
            QToolBar QToolButton#toggleImageTags:checked:!hover:!pressed {{
                border: none;
                background: transparent;
            }}
            QToolBar::separator {{
                background: {t["border"]};
                width: 1px;
                height: 1px;
                margin: 2px;
            }}
        """)

    def setUiScale(self, scale):
        self._button_size = round(26 * scale)
        self._icon_size = round(18 * scale)
        self.setIconSize(QtCore.QSize(self._icon_size, self._icon_size))
        self._apply_style()
