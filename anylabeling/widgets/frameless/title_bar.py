"""Title bar: icon, title, embedded menu bar, host buttons, window controls."""

from __future__ import annotations

import dataclasses
from typing import Callable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from .theme import FramelessTheme
from .window_buttons import (
    KIND_CLOSE,
    KIND_MAXIMIZE,
    KIND_MINIMIZE,
    KIND_RESTORE,
    WindowButton,
)


@dataclasses.dataclass
class TitleButton:
    """Declarative description of a host button placed in the title bar."""

    key: str
    text: str = ""
    icon: Optional[object] = None
    tooltip: str = ""
    role: str = "normal"  # "normal" or "primary"
    checkable: bool = False
    checked: bool = False
    on_clicked: Optional[Callable] = None
    on_toggled: Optional[Callable] = None


class TitleBar(QtWidgets.QWidget):
    """The custom title bar.  The window controls are always on the right."""

    def __init__(self, host, theme: FramelessTheme, parent=None):
        super().__init__(parent)
        self._host = host
        self._theme = theme
        self._title_buttons = {}
        self._active = True
        self._full_title = ""
        self._menu_bar = None

        self.setObjectName("FramelessTitleBar")
        self.setFixedHeight(theme.title_height)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(8, 0, 0, 0)
        self._layout.setSpacing(4)

        self.icon_label = QtWidgets.QLabel(self)
        self.icon_label.setObjectName("FramelessTitleIcon")
        self.icon_label.setFixedSize(theme.icon_size, theme.icon_size)
        self.icon_label.hide()
        self._layout.addWidget(self.icon_label)

        self.title_label = QtWidgets.QLabel(self)
        self.title_label.setObjectName("FramelessTitleText")
        self.title_label.setProperty("inactive", False)
        self._layout.addWidget(self.title_label)

        self._menu_slot = QtWidgets.QHBoxLayout()
        self._menu_slot.setContentsMargins(0, 0, 0, 0)
        self._menu_slot.setSpacing(0)
        self._layout.addLayout(self._menu_slot)

        self._layout.addStretch(1)

        self._button_area = QtWidgets.QHBoxLayout()
        self._button_area.setContentsMargins(0, 0, 0, 0)
        self._button_area.setSpacing(2)
        self._layout.addLayout(self._button_area)

        self.minimize_button = WindowButton(KIND_MINIMIZE, theme, self)
        self.minimize_button.clicked.connect(host.showMinimized)
        self.maximize_button = WindowButton(KIND_MAXIMIZE, theme, self)
        self.maximize_button.clicked.connect(host.toggle_maximize)
        self.close_button = WindowButton(KIND_CLOSE, theme, self)
        self.close_button.clicked.connect(host.close)
        self._layout.addWidget(self.minimize_button)
        self._layout.addWidget(self.maximize_button)
        self._layout.addWidget(self.close_button)

        self.setToolTip("")

    # -- content -------------------------------------------------------------
    def attach_menu_bar(self, menu_bar) -> None:
        self._menu_bar = menu_bar
        self._menu_slot.addWidget(menu_bar)

    def set_title(self, text: str) -> None:
        self._full_title = text
        self.title_label.setToolTip(text)
        self._update_title_text()

    def _update_title_text(self) -> None:
        """Elide long titles so they cannot squeeze the menus or buttons."""
        self.title_label.setMaximumWidth(
            max(80, int(self.width() * 0.35)) if self.width() else 300
        )
        available = self.title_label.maximumWidth()
        metrics = self.title_label.fontMetrics()
        self.title_label.setText(
            metrics.elidedText(
                self._full_title,
                QtCore.Qt.TextElideMode.ElideRight,
                max(available - 8, 10),
            )
        )

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._update_title_text()

    def set_icon(self, icon) -> None:
        if icon is None or (hasattr(icon, "isNull") and icon.isNull()):
            self.icon_label.hide()
            return
        self.icon_label.setPixmap(
            icon.pixmap(
                QtCore.QSize(self._theme.icon_size, self._theme.icon_size)
            )
        )
        self.icon_label.show()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.title_label.setProperty("inactive", not self._active)
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.title_label.update()

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.set_kind(
            KIND_RESTORE if maximized else KIND_MAXIMIZE
        )

    def set_theme(self, theme: FramelessTheme) -> None:
        self._theme = theme
        self.setFixedHeight(theme.title_height)
        self.icon_label.setFixedSize(theme.icon_size, theme.icon_size)
        for button in (
            self.minimize_button,
            self.maximize_button,
            self.close_button,
        ):
            button.set_theme(theme)
        for widget in self._title_buttons.values():
            if isinstance(widget, WindowButton):
                widget.set_theme(theme)

    # -- host buttons --------------------------------------------------------
    def add_button(self, spec: TitleButton):
        button = QtWidgets.QToolButton(self)
        button.setObjectName("FramelessTitleButton")
        button.setAutoRaise(True)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setToolTip(spec.tooltip or spec.text)
        button.setAccessibleName(spec.text)
        if spec.text:
            button.setText(spec.text)
        if spec.icon is not None:
            button.setIcon(spec.icon)
        if spec.role == "primary":
            button.setProperty("primary", True)
        if spec.checkable:
            button.setCheckable(True)
            button.setChecked(spec.checked)
            if spec.on_toggled is not None:
                button.toggled.connect(spec.on_toggled)
        elif spec.on_clicked is not None:
            button.clicked.connect(spec.on_clicked)
        self._button_area.addWidget(button)
        self._title_buttons[spec.key] = button
        return button

    def add_widget(self, widget, key: str = ""):
        """Place an arbitrary host widget (e.g. the operator chip)."""
        widget.setParent(self)
        self._button_area.addWidget(widget)
        if key:
            self._title_buttons[key] = widget
        return widget

    def remove_button(self, key: str) -> None:
        widget = self._title_buttons.pop(key, None)
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()

    def button(self, key: str):
        return self._title_buttons.get(key)

    # -- interaction ---------------------------------------------------------
    def _begin_drag(self, event) -> None:
        host = self._host
        handle = host.windowHandle()
        if handle is None:
            return
        if host.isMaximized():
            # Restore first so the window follows the cursor instead of
            # staying snapped to the screen edge.
            ratio = 0.5
            if host.width():
                ratio = (event.globalPosition().x() - host.x()) / host.width()
                ratio = min(max(ratio, 0.05), 0.95)
            host.showNormal()
            new_x = event.globalPosition().x() - ratio * host.width()
            new_y = event.globalPosition().y() - self.height() / 2
            host.move(int(new_x), int(new_y))
        handle.startSystemMove()

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_drag(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._host.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def build_context_menu(self):
        """Build the title bar context menu (also used by tests)."""
        host = self._host
        menu = QtWidgets.QMenu(self)
        if host.isMaximized() or host.isFullScreen():
            restore = menu.addAction(self.tr("Restore"))
            restore.triggered.connect(host.restore_window)
        else:
            maximize = menu.addAction(self.tr("Maximize"))
            maximize.triggered.connect(host.showMaximized)
        minimize = menu.addAction(self.tr("Minimize"))
        minimize.triggered.connect(host.showMinimized)
        # Full screen is not part of this menu: the host places a single
        # toggle in the title bar (and the View menu) instead, so there is no
        # second entry point that can drift out of sync.
        if self._menu_bar is not None:
            menus = self._menu_bar.top_level_menus()
            if menus:
                menu.addSeparator()
                visibility = menu.addMenu(self.tr("Menus"))
                for top in menus:
                    top_action = top.menuAction()
                    title = top.title()
                    toggle = visibility.addAction(title)
                    toggle.setCheckable(True)
                    toggle.setChecked(top_action.isVisible())
                    toggle.triggered.connect(
                        lambda checked, name=title: (
                            self._menu_bar.set_menu_visible(name, checked)
                        )
                    )
        menu.addSeparator()
        close = menu.addAction(self.tr("Close"))
        close.triggered.connect(host.close)
        return menu

    def contextMenuEvent(self, event):  # noqa: N802 - Qt naming
        menu = self.build_context_menu()
        menu.exec(event.globalPos())
        event.accept()
