"""This module defines the main application window"""

import os

from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QMainWindow,
    QMenu,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..app_info import __appdescription__, __appname__, __version__
from .labeling.label_wrapper import LabelingWrapper

# Toolbar positions supported by the labeling toolbar. They are persisted by
# name so the saved value stays readable and independent of Qt enum values.
_TOOLBAR_AREA_NAMES = {
    "top": QtCore.Qt.ToolBarArea.TopToolBarArea,
    "left": QtCore.Qt.ToolBarArea.LeftToolBarArea,
}


def _is_wsl_environment() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as file_obj:
            return "microsoft" in file_obj.read().lower()
    except OSError:
        return False


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(
        self,
        app,
        config=None,
        filename=None,
        output=None,
        output_file=None,
        output_dir=None,
    ):
        super().__init__()
        self.app = app
        self.config = config

        self.setContentsMargins(0, 0, 0, 0)
        self.setWindowTitle(__appname__)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 2, 10, 10)
        self.labeling_widget = LabelingWrapper(
            self,
            config=config,
            filename=filename,
            output=output,
            output_file=output_file,
            output_dir=output_dir,
        )
        main_layout.addWidget(self.labeling_widget)
        widget = QWidget()
        widget.setLayout(main_layout)
        self.setCentralWidget(widget)
        self.settings = self.labeling_widget.view.settings
        self._install_toolbar()
        self._is_wsl_environment = _is_wsl_environment()
        if self._is_wsl_environment:
            self.settings.remove("window/size")
            self.settings.remove("window/position")
            self.settings.remove("window/state")
            self.settings.sync()

        status_bar = QStatusBar()
        status_bar.showMessage(
            f"{__appname__} v{__version__} - {__appdescription__}"
        )
        self.setStatusBar(status_bar)
        self._restore_window_geometry()

    # -- toolbar docking ---------------------------------------------------
    def _install_toolbar(self):
        """Dock the labeling toolbar into this window.

        The toolbar is a real ``QToolBar`` that can be docked at the top or in
        the left tool-bar area. Qt 6 dropped the draggable toolbar handle and
        its floating path mis-sizes floating windows on Windows, so floating
        is disabled and the position is changed through the toolbar/view
        menus instead.

        The position is persisted explicitly in ``window/toolbar_area``
        rather than through ``QMainWindow.saveState``: Qt restores a floating
        toolbar from a saved state even when ``setFloatable(False)`` is set
        (``QToolBarPrivate::setWindowState`` ignores the flag). A floating
        geometry restored from an older state explodes into huge window sizes
        on Windows (``QWindowsWindow::setGeometry`` warnings followed by
        ``CreateDIBSection`` failures), so legacy ``window/state`` data is
        dropped on startup.
        """
        toolbar = getattr(self.labeling_widget.view, "tools", None)
        # Legacy QMainWindow state is dropped even if the toolbar is missing:
        # it may contain a floating toolbar geometry that breaks the window.
        self.settings.remove("window/state")
        if toolbar is None:
            return
        if not toolbar.objectName():
            toolbar.setObjectName("ToolsToolBar")
        self._toolbar = toolbar
        self._toolbar_area = self._load_toolbar_area()
        self.addToolBar(self._toolbar_area, toolbar)
        toolbar.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        toolbar.customContextMenuRequested.connect(
            self._show_toolbar_menu
        )
        self._install_toolbar_menu_actions(toolbar)
        self.set_toolbar_visible(self._load_toolbar_visibility())

    def _load_toolbar_area(self):
        saved = self.settings.value("window/toolbar_area", "top")
        return _TOOLBAR_AREA_NAMES.get(
            str(saved), QtCore.Qt.ToolBarArea.TopToolBarArea
        )

    def _save_toolbar_area(self):
        for name, area in _TOOLBAR_AREA_NAMES.items():
            if area == getattr(self, "_toolbar_area", None):
                self.settings.setValue("window/toolbar_area", name)
                return

    def _load_toolbar_visibility(self):
        return self.settings.value("window/toolbar_visible", True, type=bool)

    def _save_toolbar_visibility(self):
        self.settings.setValue(
            "window/toolbar_visible", bool(getattr(self, "_toolbar_visible", True))
        )

    def _install_toolbar_menu_actions(self, toolbar):
        view_menu = getattr(self.labeling_widget.view, "menus", None)
        view_menu = getattr(view_menu, "view", None)
        if view_menu is None:
            return
        view_menu.addSeparator()
        dock_top = view_menu.addAction(
            self.tr("Dock Toolbar at Top")
        )
        dock_top.triggered.connect(
            lambda: self.dock_toolbar(
                QtCore.Qt.ToolBarArea.TopToolBarArea
            )
        )
        dock_left = view_menu.addAction(
            self.tr("Dock Toolbar at Left")
        )
        dock_left.triggered.connect(
            lambda: self.dock_toolbar(
                QtCore.Qt.ToolBarArea.LeftToolBarArea
            )
        )
        toggle_toolbar = view_menu.addAction(self.tr("Show Toolbar"))
        toggle_toolbar.setCheckable(True)
        toggle_toolbar.setChecked(toolbar.isVisible())
        toggle_toolbar.triggered.connect(self.set_toolbar_visible)
        self._toolbar_view_menu_action = toggle_toolbar

    def _show_toolbar_menu(self, position):
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None:
            return
        menu = QMenu(self)
        dock_top = menu.addAction(self.tr("Dock Toolbar at Top"))
        dock_left = menu.addAction(self.tr("Dock Toolbar at Left"))
        menu.addSeparator()
        hide_action = menu.addAction(self.tr("Hide Toolbar"))
        chosen = menu.exec(toolbar.mapToGlobal(position))
        if chosen == dock_top:
            self.dock_toolbar(QtCore.Qt.ToolBarArea.TopToolBarArea)
        elif chosen == dock_left:
            self.dock_toolbar(QtCore.Qt.ToolBarArea.LeftToolBarArea)
        elif chosen == hide_action:
            self.set_toolbar_visible(False)

    def dock_toolbar(self, area):
        """Move the labeling toolbar to ``area`` (top or left)."""
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None:
            return
        if area not in _TOOLBAR_AREA_NAMES.values():
            area = QtCore.Qt.ToolBarArea.TopToolBarArea
        self._toolbar_area = area
        if not toolbar.isVisible():
            toolbar.show()
        self.addToolBar(area, toolbar)
        self._save_toolbar_area()

    def set_toolbar_visible(self, visible):
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None:
            return
        self._toolbar_visible = bool(visible)
        toolbar.setVisible(self._toolbar_visible)
        action = getattr(self, "_toolbar_view_menu_action", None)
        if action is not None:
            action.setChecked(self._toolbar_visible)
        self._save_toolbar_visibility()

    def show_toolbar(self):
        self.set_toolbar_visible(True)
        self.dock_toolbar(QtCore.Qt.ToolBarArea.TopToolBarArea)

    def closeEvent(self, event):
        self.labeling_widget.closeEvent(event)
        if not event.isAccepted():
            return
        if hasattr(self, "update_controller"):
            self.update_controller.prepare_for_close()
        if self._is_wsl_environment:
            self.settings.remove("window/size")
            self.settings.remove("window/position")
            self.settings.remove("window/state")
        else:
            self.settings.setValue("window/size", self.size())
            self.settings.setValue("window/position", self.pos())
            self._save_toolbar_area()
            self._save_toolbar_visibility()
            # Never write a QMainWindow state again: it can contain a floating
            # toolbar whose restored geometry breaks the window on Windows.
            self.settings.remove("window/state")
        super().closeEvent(event)

    def _restore_window_geometry(self):
        if self._is_wsl_environment:
            return
        if self.settings.contains("window/size"):
            size = self.settings.value("window/size", type=QtCore.QSize)
            if isinstance(size, QtCore.QSize) and size.isValid():
                self.resize(size)
        if self.settings.contains("window/position"):
            position = self.settings.value(
                "window/position", type=QtCore.QPoint
            )
            if isinstance(position, QtCore.QPoint):
                self.move(position)
