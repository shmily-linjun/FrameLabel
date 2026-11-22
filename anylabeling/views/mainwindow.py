"""This module defines the main application window"""

import os

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import (
    QMenu,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..app_info import __appname__
from ..widgets.frameless import FramelessWindow, window_state
from .labeling.label_wrapper import LabelingWrapper
from .labeling.pointcloud.icons import get_icon
from .labeling.utils.theme import get_theme
from .labeling.widgets.toolbar import ToolBarScrollArea

# Toolbar positions supported by the labeling toolbar. They are persisted by
# name so the saved value stays readable and independent of Qt enum values.
_TOOLBAR_AREA_NAMES = {
    "top": QtCore.Qt.ToolBarArea.TopToolBarArea,
    "left": QtCore.Qt.ToolBarArea.LeftToolBarArea,
}


class _StatusTipFilter(QtCore.QObject):
    """Route Qt status tips to the custom status bar.

    ``QMainWindow`` handles ``QStatusTipEvent`` in C++ and calls the native
    ``QStatusBar::showMessage()``, which would hide the document label.  The
    filter consumes the event and shows the tip in the custom message label
    instead, keeping ``[x,y|path]`` visible.
    """

    def __init__(self, status_bar, parent=None):
        super().__init__(parent)
        self._status_bar = status_bar

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if event.type() == QtCore.QEvent.Type.StatusTip:
            tip = event.tip() if hasattr(event, "tip") else ""
            if tip:
                self._status_bar.showMessage(tip, 3000)
            else:
                self._status_bar.clearMessage()
            return True
        return False


class DocumentStatusBar(QStatusBar):
    """Status bar that keeps the document label and transient messages apart.

    ``QStatusBar.showMessage()`` normally hides widgets added with
    ``addWidget()``.  This subclass routes messages to a dedicated label and
    keeps the document label (``[x,y|path]``) visible on the left at all
    times, while ``showMessage`` / ``clearMessage`` / ``currentMessage`` keep
    their usual semantics for callers.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.message_label = QtWidgets.QLabel("")
        self.message_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.message_label.hide()
        self.addWidget(self.message_label, 0)

        self.document_label = QtWidgets.QLabel("")
        self.document_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.document_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.document_label.setMinimumWidth(0)
        self.addWidget(self.document_label, 1)

        self._message = ""
        self._message_timer = QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.clearMessage)

    def showMessage(self, message, timeout=0):  # noqa: N802 - Qt naming
        self._message = message or ""
        self.message_label.setText(self._message)
        self.message_label.setVisible(bool(self._message))
        self._message_timer.stop()
        if timeout and timeout > 0:
            self._message_timer.start(int(timeout))

    def clearMessage(self):  # noqa: N802 - Qt naming
        self._message = ""
        self.message_label.clear()
        self.message_label.hide()
        self._message_timer.stop()

    def currentMessage(self):  # noqa: N802 - Qt naming
        return self._message


def _is_wsl_environment() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as file_obj:
            return "microsoft" in file_obj.read().lower()
    except OSError:
        return False


def _resolve_frameless(config) -> bool:
    """Decide the window chrome for this launch.

    Precedence: environment override, then the ``frameless`` config key,
    then the default (frameless).  Runtime switching is intentionally not
    supported; a restart is required.
    """
    override = os.environ.get("XANYLABELING_NATIVE_FRAME", "").strip().lower()
    if override in ("1", "true", "yes", "on"):
        return False
    if override in ("0", "false", "no", "off"):
        return True
    try:
        return bool(config.get("frameless", True))
    except (AttributeError, TypeError):
        return True


class MainWindow(FramelessWindow):
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
        super().__init__(frameless=_resolve_frameless(config))
        self.app = app
        self.config = config
        self.set_app_title(__appname__)
        self.set_display_title(__appname__)
        self.apply_theme(get_theme())

        self.setContentsMargins(0, 0, 0, 0)

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
        self.set_content_widget(widget)
        self.settings = self.labeling_widget.view.settings
        self._install_toolbar()
        self._install_window_actions()
        self._is_wsl_environment = _is_wsl_environment()
        if self._is_wsl_environment:
            self.settings.remove("window/size")
            self.settings.remove("window/position")
            self.settings.remove("window/state")
            self.settings.sync()

        status_bar = DocumentStatusBar()
        self.document_status_label = status_bar.document_label
        self.setStatusBar(status_bar)
        self._status_tip_filter = _StatusTipFilter(status_bar, self)
        app_instance = QtWidgets.QApplication.instance()
        if app_instance is not None:
            app_instance.installEventFilter(self._status_tip_filter)
        self._install_operator_chrome()
        self._install_fullscreen_button()
        self._restore_menu_visibility()
        self._restore_window_geometry()

    def _install_window_actions(self):
        """Add window-level actions (full screen) to the View menu."""
        view = getattr(self.labeling_widget, "view", None)
        view_menu = getattr(getattr(view, "menus", None), "view", None)
        if view_menu is None:
            return
        view_menu.addSeparator()
        view_menu.addAction(self.fullscreen_action)

    def _install_fullscreen_button(self):
        """Place the single full-screen toggle in the window chrome.

        Frameless mode puts it in the title bar next to the window controls;
        native mode falls back to the labeling toolbar.  One checkable action
        drives both the button and the View menu entry, so the two never
        disagree about the current state.
        """
        button = QtWidgets.QToolButton(self)
        button.setObjectName("FramelessTitleButton")
        button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        button.setFixedSize(30, 24)
        button.setDefaultAction(self.fullscreen_action)
        self._fullscreen_button = button
        self._sync_fullscreen_button(self.isFullScreen())
        if self.frameless:
            self.add_title_widget(button, key="window-control-fullscreen")
        else:
            toolbar = getattr(self, "_toolbar", None)
            if toolbar is not None:
                action = QtWidgets.QWidgetAction(self)
                action.setDefaultWidget(button)
                toolbar.addAction(action)
        self.fullscreen_changed.connect(self._sync_fullscreen_button)

    def _sync_fullscreen_button(self, fullscreen: bool):
        """Reflect the full-screen state in the shared action's icon/text."""
        theme = get_theme()
        icon = get_icon(
            "restore-view" if fullscreen else "expand-view",
            theme["text"],
            theme["primary"],
        )
        text = (
            self.tr("Exit Full Screen")
            if fullscreen
            else self.tr("Full Screen")
        )
        self.fullscreen_action.setIcon(icon)
        self.fullscreen_action.setText(text)
        self.fullscreen_action.setToolTip(text)
        button = getattr(self, "_fullscreen_button", None)
        if button is not None:
            button.setAccessibleName(text)
            button.setToolTip(text)

    def _restore_menu_visibility(self):
        state = self.settings.value(
            "frameless/menu_visibility", {}, type=dict
        )
        if state:
            self.restore_menu_visibility(state)
        self.menu_visibility_changed.connect(self._save_menu_visibility)

    def _save_menu_visibility(self, state):
        self.settings.setValue("frameless/menu_visibility", state)

    def update_document_status(self, text: str) -> None:
        """Show the current image summary in the status bar."""
        label = getattr(self, "document_status_label", None)
        if label is not None:
            label.setText(text)

    def _install_operator_chrome(self):
        """Place the operator chip and attribution into the window chrome.

        Frameless mode puts the chip in the custom title bar; native mode
        keeps the menu-bar corner widget.  The attribution text always goes
        to the status bar, so neither mode costs canvas height.
        """
        view = getattr(self.labeling_widget, "view", None)
        if view is None:
            return
        bar = getattr(view, "operator_bar", None)
        if bar is not None:
            if self.frameless:
                self.add_title_widget(bar, key="operator")
            else:
                self.menuBar().setCornerWidget(
                    bar, QtCore.Qt.Corner.TopRightCorner
                )
            bar.show()
        attribution = getattr(view, "attribution_label", None)
        if attribution is not None:
            self.statusBar().addPermanentWidget(attribution)
            attribution.show()
        controls = getattr(view, "window_control_buttons", ())
        for index, button in enumerate(controls):
            if self.frameless:
                self.add_title_widget(button, key=f"window-control-{index}")
            else:
                action = QtWidgets.QWidgetAction(self)
                action.setDefaultWidget(button)
                self._toolbar.addAction(action)

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
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        toolbar.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

        # A dock widget hosting a scroll area is used instead of a docked
        # QToolBar: Qt only scrolls toolbars through the hidden extension
        # button, while the requirement is one scrollbar for the complete
        # toolbar (vertical on the left, horizontal at the top).
        self._toolbar_scroll = ToolBarScrollArea(self)
        self._toolbar_scroll.setObjectName("ToolsToolBarScroll")
        self._toolbar_scroll.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignTop
        )
        self._toolbar_scroll.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._toolbar_scroll.viewport().setAutoFillBackground(False)
        self._toolbar_scroll.setWidget(toolbar)
        self._toolbar_dock = QtWidgets.QDockWidget(self)
        self._toolbar_dock.setObjectName("ToolsDock")
        self._toolbar_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        )
        self._toolbar_dock.setTitleBarWidget(QtWidgets.QWidget(self._toolbar_dock))
        self._toolbar_dock.setWidget(self._toolbar_scroll)
        self._toolbar_area = self._load_toolbar_area()
        self._apply_toolbar_area(self._toolbar_area)
        toolbar.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        toolbar.customContextMenuRequested.connect(
            self._show_toolbar_menu
        )
        self._install_toolbar_menu_actions(toolbar)
        self.set_toolbar_visible(self._load_toolbar_visibility())

    def _apply_toolbar_area(self, area):
        """Orient the toolbar and scrollbar for the requested dock position."""
        toolbar = getattr(self, "_toolbar", None)
        scroll = getattr(self, "_toolbar_scroll", None)
        dock = getattr(self, "_toolbar_dock", None)
        if toolbar is None or scroll is None or dock is None:
            return
        if area == _TOOLBAR_AREA_NAMES["left"]:
            toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
            scroll.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            dock_area = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
        else:
            area = _TOOLBAR_AREA_NAMES["top"]
            toolbar.setOrientation(QtCore.Qt.Orientation.Horizontal)
            scroll.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            dock_area = QtCore.Qt.DockWidgetArea.TopDockWidgetArea
        toolbar.adjustSize()
        view = getattr(self.labeling_widget, "view", None)
        if view is not None and hasattr(view, "refresh_toolbar_geometry"):
            view.refresh_toolbar_geometry()
        scroll.updateGeometry()
        self.addDockWidget(dock_area, dock)
        dock.show()

    def _load_toolbar_area(self):
        # One-time migration: the toolbar used to default to the top area.
        # Users who never chose an area get the new left default; an explicit
        # later choice is persisted and respected.
        scheme = self.settings.value("window/toolbar_area_scheme", 1, type=int)
        if scheme < 3:
            self.settings.setValue("window/toolbar_area_scheme", 3)
            self.settings.setValue("window/toolbar_area", "left")
            self.settings.sync()
            return _TOOLBAR_AREA_NAMES["left"]
        saved = self.settings.value("window/toolbar_area", "left")
        return _TOOLBAR_AREA_NAMES.get(
            str(saved), QtCore.Qt.ToolBarArea.LeftToolBarArea
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
        self._apply_toolbar_area(area)
        self.set_toolbar_visible(True)
        self._save_toolbar_area()

    def set_toolbar_visible(self, visible):
        dock = getattr(self, "_toolbar_dock", None)
        if dock is None:
            return
        self._toolbar_visible = bool(visible)
        dock.setVisible(self._toolbar_visible)
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
            self.settings.setValue(
                "window/maximized", bool(self.isMaximized())
            )
            self._save_toolbar_area()
            self._save_toolbar_visibility()
            # Never write a QMainWindow state again: it can contain a floating
            # toolbar whose restored geometry breaks the window on Windows.
            self.settings.remove("window/state")
        super().closeEvent(event)

    def _restore_window_geometry(self):
        if self._is_wsl_environment:
            return
        size = None
        position = None
        if self.settings.contains("window/size"):
            candidate = self.settings.value(
                "window/size", type=QtCore.QSize
            )
            if isinstance(candidate, QtCore.QSize) and candidate.isValid():
                size = candidate
        if self.settings.contains("window/position"):
            candidate = self.settings.value(
                "window/position", type=QtCore.QPoint
            )
            if isinstance(candidate, QtCore.QPoint):
                position = candidate
        if size is not None and position is not None:
            rect = window_state.clamp_geometry(
                QtCore.QRect(position, size),
                QtWidgets.QApplication.screens(),
            )
            self.resize(rect.size())
            self.move(rect.topLeft())
        elif size is not None:
            self.resize(size)
        elif position is not None:
            self.move(position)
        if self.settings.value("window/maximized", False, type=bool):
            self.showMaximized()
