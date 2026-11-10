"""Defines toolbar for anylabeling, including"""

from PyQt6 import QtCore, QtGui, QtWidgets
from anylabeling.views.labeling.utils.theme import get_theme


class ToolBarScrollArea(QtWidgets.QScrollArea):
    """Kept for backwards compatibility with existing imports.

    The horizontal toolbar is now a dockable ``QToolBar`` that manages its
    own overflow through the extension button, so the scroll area wrapper is
    no longer used by the labeling widget.
    """

    def wheelEvent(self, event):
        scroll_bar = self.horizontalScrollBar()
        if scroll_bar.maximum() > scroll_bar.minimum():
            QtWidgets.QApplication.sendEvent(scroll_bar, event)
            return
        super().wheelEvent(event)


class ToolBar(QtWidgets.QToolBar):
    """Dockable toolbar widget for labeling tool.

    A real ``QToolBar`` added to the ``QMainWindow`` so it can be docked at
    the top or in the left tool-bar area. Floating is intentionally disabled:
    Qt 6's floating-toolbar path mis-sizes the floating window on Windows
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
        self.setIconSize(
            QtCore.QSize(self._icon_size, self._icon_size),
        )
        self._apply_style()

    def _apply_style(self):
        t = get_theme()
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
                padding: 0px;
                margin: 0px;
                width: {self._button_size}px;
                height: {self._button_size}px;
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
