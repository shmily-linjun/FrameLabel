"""Menu bar used inside the frameless title bar.

It is a real ``QMenuBar`` so keyboard access, sub-menus, shortcut display and
Qt's built-in overflow ("extension") button keep working.  The class adds:

* ``add_menu`` returning the created ``QMenu`` (any nesting depth afterwards);
* per-menu visibility toggling with a context menu on the bar background;
* a ``menu_visibility_changed`` signal so the host can persist the state.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class FrameMenuBar(QtWidgets.QMenuBar):
    """Real menu bar with user-toggleable top-level menus."""

    menu_visibility_changed = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None, in_window: bool = True):
        super().__init__(parent)
        self.setObjectName("FramelessMenuBar")
        # macOS uses a global menu bar in native mode; keep it there.  In
        # frameless mode the bar must live inside the custom title bar.
        self.setNativeMenuBar(not in_window)

    # -- menus ---------------------------------------------------------------
    def add_menu(self, title: str) -> QtWidgets.QMenu:
        """Create and register a top-level menu, returning it."""
        return self.addMenu(title)

    def top_level_menus(self) -> list:
        menus = []
        for action in self.actions():
            menu = action.menu()
            if menu is not None:
                menus.append(menu)
        return menus

    def menu_titles(self) -> list:
        return [menu.title() for menu in self.top_level_menus()]

    # -- visibility ----------------------------------------------------------
    def _action_for(self, title: str):
        for action in self.actions():
            if action.menu() is not None and action.text() == title:
                return action
        return None

    def set_menu_visible(self, title: str, visible: bool) -> None:
        action = self._action_for(title)
        if action is None or action.isVisible() == bool(visible):
            return
        action.setVisible(bool(visible))
        self.menu_visibility_changed.emit(self.visibility_state())

    def visibility_state(self) -> dict:
        return {
            action.text(): action.isVisible()
            for action in self.actions()
            if action.menu() is not None
        }

    def restore_visibility(self, state) -> None:
        if not isinstance(state, dict):
            return
        for action in self.actions():
            if action.menu() is None:
                continue
            title = action.text()
            if title in state:
                action.setVisible(bool(state[title]))

    def show_all_menus(self) -> None:
        changed = False
        for action in self.actions():
            if action.menu() is None:
                continue
            if not action.isVisible():
                action.setVisible(True)
                changed = True
        if changed:
            self.menu_visibility_changed.emit(self.visibility_state())

    # -- context menu --------------------------------------------------------
    def contextMenuEvent(self, event):  # noqa: N802 - Qt naming
        menu = QtWidgets.QMenu(self)
        for action in self.actions():
            if action.menu() is None:
                continue
            toggle = menu.addAction(action.text())
            toggle.setCheckable(True)
            toggle.setChecked(action.isVisible())
            toggle.triggered.connect(
                lambda checked, title=action.text(): self.set_menu_visible(
                    title, checked
                )
            )
        if menu.actions():
            menu.addSeparator()
            show_all = menu.addAction(self.tr("Show All Menus"))
            show_all.triggered.connect(self.show_all_menus)
        menu.exec(event.globalPos())
        event.accept()
