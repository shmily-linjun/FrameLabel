"""Title-bar chip that shows the current dataset and offers quick actions.

The chip lives in the frameless title bar (or the toolbar in native mode) and
is the contextual counterpart of the dataset center: it answers "which dataset
am I in?" and lets the operator jump to the center, switch datasets or close
the current one.  See the design doc §4.7 (fork.56).
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from ..utils.theme import get_theme


def _elide(text: str, limit: int = 28) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


class DatasetChip(QtWidgets.QToolButton):
    """Small pill showing the open dataset; its menu is built lazily."""

    open_center_requested = QtCore.pyqtSignal()
    open_dataset_requested = QtCore.pyqtSignal(str)
    close_dataset_requested = QtCore.pyqtSignal()

    def __init__(self, registry_provider=None, parent=None):
        super().__init__(parent)
        self._registry_provider = registry_provider
        self._root = None
        self._name = ""
        self.setObjectName("DatasetChip")
        self.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setMenu(QtWidgets.QMenu(self))
        self.menu().aboutToShow.connect(self._rebuild_menu)
        self.set_dataset(None, None)
        self._apply_style()

    # -- state -------------------------------------------------------------
    @property
    def dataset_root(self):
        return self._root

    def set_dataset(self, name: str | None, root: str | None) -> None:
        """Show ``name``/``root``; ``None`` means no dataset is open."""

        self._root = root or None
        self._name = name or ""
        if not self._root:
            self.setText(self.tr("No dataset"))
            self.setToolTip(self.tr("No dataset is open"))
        else:
            shown = _elide(self._name) if self._name else _elide(
                self._root
            )
            self.setText(self.tr("Dataset: %s") % shown)
            self.setToolTip(
                self.tr("Current dataset: %s") % self._root
            )
        self._apply_style()

    def _apply_style(self) -> None:
        theme = get_theme()
        self.setStyleSheet(
            "QToolButton#DatasetChip {"
            f" color: {theme['text']};"
            f" background: {theme['surface']};"
            f" border: 1px solid {theme['border']};"
            " border-radius: 9px;"
            " padding: 2px 8px;"
            " font-size: 11px;"
            "}"
            "QToolButton#DatasetChip::menu-indicator {"
            " width: 0px;"
            "}"
        )

    # -- menu --------------------------------------------------------------
    def _entries(self):
        if self._registry_provider is None:
            return []
        try:
            registry = self._registry_provider()
            return [
                entry
                for entry in registry.list()
                if entry.state == "active"
            ]
        except Exception:  # noqa: BLE001 - the menu must still open
            return []

    def _rebuild_menu(self) -> None:
        menu = self.menu()
        menu.clear()
        if self._root:
            info = menu.addAction(
                self.tr("Current: %s") % _elide(self._name or self._root)
            )
            info.setEnabled(False)
            menu.addSeparator()
        center_action = menu.addAction(self.tr("Dataset Center…"))
        center_action.triggered.connect(
            lambda: self.open_center_requested.emit()
        )
        entries = [
            entry
            for entry in self._entries()
            if not self._root
            or entry.root_path.casefold() != self._root.casefold()
        ]
        switch_menu = menu.addMenu(self.tr("Switch dataset"))
        if entries:
            for entry in entries[:20]:
                label = entry.display_name or entry.uuid[:8]
                action = switch_menu.addAction(label)
                action.setToolTip(entry.db_path)
                action.triggered.connect(
                    lambda _checked=False, root=entry.root_path: (
                        self.open_dataset_requested.emit(root)
                    )
                )
        else:
            empty = switch_menu.addAction(self.tr("No other datasets"))
            empty.setEnabled(False)
        menu.addSeparator()
        close_action = menu.addAction(self.tr("Close dataset"))
        close_action.setEnabled(bool(self._root))
        close_action.triggered.connect(
            lambda: self.close_dataset_requested.emit()
        )
