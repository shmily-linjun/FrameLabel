"""Plain list of image classes (the "Classes" tab).

Formerly this widget painted a checkbox per class (class visibility) and a
lock icon, with a panel header holding show/hide and lock-all buttons. The
tab is now a plain ``QListWidget``: the list only shows class names and
supports selection. The ``lock_states`` dictionary is kept because the label
manager dialog still sets a per-class lock policy; it is no longer rendered
in the list.
"""

from PyQt6 import QtCore, QtGui, QtWidgets

from .escapable_qlist_widget import EscapableQListWidget
from .label_list_widget import LOCKED_ROLE


class UniqueLabelQListWidget(EscapableQListWidget):
    # Retained for API compatibility; the plain list no longer emits them.
    items_lock_requested = QtCore.pyqtSignal(list)
    label_visibility_changed = QtCore.pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lock_states = {}
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )

    def find_items_by_label(self, label):
        items = []
        for row in range(self.count()):
            item = self.item(row)
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == label:
                items.append(item)
        return items

    def create_item_from_label(self, label):
        item = QtWidgets.QListWidgetItem()
        item.setData(QtCore.Qt.ItemDataRole.UserRole, label)
        item.setFlags(
            item.flags() & ~QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        return item

    def set_item_label(self, item, label, color=None, opacity=255):
        item.setText(str(label))
        if color is not None:
            item.setBackground(QtGui.QColor(*color, opacity))
        self.set_item_locked(item, self.lock_states.get(label, False))

    def set_item_locked(self, item, locked):
        item.setData(LOCKED_ROLE, bool(locked))

    def update_item_color(self, label, color, opacity=255):
        for item in self.find_items_by_label(label):
            item.setBackground(QtGui.QColor(*color, opacity))

    def remove_items_by_label(self, label):
        for item in reversed(self.find_items_by_label(label)):
            self.takeItem(self.row(item))
