"""Plain list widgets for the objects/classes panels.

The main window's right-side tabs used to embed custom-painted list views
with per-row checkboxes, lock icons and a panel header with show/hide and
lock-all buttons. Those controls were removed in favour of plain
``QListWidget`` based lists (fork requirement: objects / classes tabs show a
plain list and only keep selection interaction).

The classes and helpers keep the small API surface that the labeling widget
and dialogs already rely on (shape lookup, selection helpers, lock state
storage for the label manager). The lock state is no longer painted in the
list; it is only kept as item data for the label-manager session policy.
"""

from PyQt6 import QtCore, QtGui, QtWidgets


LOCKED_ROLE = QtCore.Qt.ItemDataRole.UserRole.value + 1


class LabelListWidgetItem(QtWidgets.QListWidgetItem):
    """Plain list item that carries the :class:`Shape` it represents."""

    def __init__(self, text=None, shape=None):
        super().__init__(text or "")
        self.set_shape(shape)
        self.setFlags(
            self.flags() & ~QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )

    def clone(self):
        return LabelListWidgetItem(self.text(), self.shape())

    def set_shape(self, shape):
        self.setData(QtCore.Qt.ItemDataRole.UserRole, shape)

    def shape(self):
        return self.data(QtCore.Qt.ItemDataRole.UserRole)

    def set_locked(self, locked):
        self.setData(LOCKED_ROLE, bool(locked))

    def is_locked(self):
        return bool(self.data(LOCKED_ROLE))

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return f'{self.__class__.__name__}("{self.text()!r}")'


class LabelListWidget(QtWidgets.QListWidget):
    """Plain list of objects; selection and double-click are the only UI."""

    item_double_clicked = QtCore.pyqtSignal(object)
    item_selection_changed = QtCore.pyqtSignal(list, list)
    item_changed = QtCore.pyqtSignal(object)
    items_lock_requested = QtCore.pyqtSignal(list)
    item_dropped = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selection_snapshot = []
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.setMouseTracking(True)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemChanged.connect(self._on_item_changed)

    # -- signals -------------------------------------------------------
    def _on_item_double_clicked(self, item):
        self.item_double_clicked.emit(item)

    def _on_selection_changed(self):
        selected = self.selected_items()
        deselected = [
            item
            for item in self._selection_snapshot
            if item not in selected
        ]
        self._selection_snapshot = list(selected)
        self.item_selection_changed.emit(selected, deselected)

    def _on_item_changed(self, item):
        self.item_changed.emit(item)

    # -- Qt container protocol ----------------------------------------
    def __len__(self):
        return self.count()

    def __getitem__(self, index):
        return self.item(index)

    def __iter__(self):
        for row in range(self.count()):
            yield self.item(row)

    # -- helpers -------------------------------------------------------
    def selected_items(self):
        return list(self.selectedItems())

    def select_item(self, item):
        item.setSelected(True)

    def scroll_to_item(self, item):
        self.scrollToItem(item)

    def add_iem(self, item):
        if not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem")
        self.addItem(item)

    def remove_item(self, item):
        self.takeItem(self.row(item))

    def find_item_by_shape(self, shape):
        for item in self:
            if item.shape() is shape:
                return item
        return None

    def item_at_index(self, index):
        return self.item(index)
