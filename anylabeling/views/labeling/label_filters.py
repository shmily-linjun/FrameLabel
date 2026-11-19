"""Class/group-ID filters and the visible label check boxes.

The classes tab, the two filter combo boxes and the canvas context
menu share the same per-label visibility state; the statistics tab
reuses the same filter values.  These helpers used to live on
``LabelingWidget``.
"""

import functools

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from . import utils
from .constants import LABEL_OPACITY

class LabelFilterController:
    """Label/group-ID filter menus and visibility state."""

    def __init__(self, host):
        self.host = host

    def _append_filter_submenus(
        self, parent_menu, prepend=False, after_filter_actions=None
    ):
        label_menu = QtWidgets.QMenu(self.host.tr("Filter by Label"), parent_menu)
        gid_menu = QtWidgets.QMenu(self.host.tr("Filter by Group ID"), parent_menu)
        if prepend and parent_menu.actions():
            first_action = parent_menu.actions()[0]
            parent_menu.insertMenu(first_action, label_menu)
            parent_menu.insertMenu(first_action, gid_menu)
            parent_menu.insertSeparator(first_action)
            if after_filter_actions:
                for action in after_filter_actions:
                    parent_menu.insertAction(first_action, action)
                parent_menu.insertSeparator(first_action)
        else:
            parent_menu.addSeparator()
            parent_menu.addMenu(label_menu)
            parent_menu.addMenu(gid_menu)
            if after_filter_actions:
                parent_menu.addSeparator()
                utils.add_actions(parent_menu, after_filter_actions)
        return label_menu, gid_menu

    def _populate_label_filter_menu(self, menu):
        menu.clear()
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)
        current_label = self.host.label_filter_combobox.text_box.currentText()
        for label in self.host.label_filter_combobox.items:
            text = self.host.tr("All Labels") if label == "" else label
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(label == current_label)
            action.triggered.connect(
                functools.partial(self.host.set_label_filter_value, label)
            )
            action_group.addAction(action)

    def _populate_gid_filter_menu(self, menu):
        menu.clear()
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)
        current_gid = self.host.gid_filter_combobox.gid_box.currentText()
        for gid in self.host.gid_filter_combobox.items:
            text = self.host.tr("All Group IDs") if gid == "-1" else gid
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(gid == current_gid)
            action.triggered.connect(
                functools.partial(self.host.set_gid_filter_value, gid)
            )
            action_group.addAction(action)

    def refresh_filter_menus(self):
        self.host.update_combo_box(block_signal=True)
        self.host.update_gid_box(block_signal=True)

        menus = [
            (self.host.canvas_label_filter_menu_0, self.host.canvas_gid_filter_menu_0),
            (self.host.canvas_label_filter_menu_1, self.host.canvas_gid_filter_menu_1),
        ]
        for label_menu, gid_menu in menus:
            if label_menu is not None:
                self.host._populate_label_filter_menu(label_menu)
            if gid_menu is not None:
                self.host._populate_gid_filter_menu(gid_menu)

    def set_label_filter_value(
        self, label, _checked=False, block_signal=False
    ):
        index = self.host.label_filter_combobox.text_box.findText(str(label))
        if index < 0:
            index = self.host.label_filter_combobox.text_box.findText("")
        if index >= 0:
            blocker = None
            if block_signal:
                blocker = QtCore.QSignalBlocker(
                    self.host.label_filter_combobox.text_box
                )
            self.host.label_filter_combobox.text_box.setCurrentIndex(index)
            del blocker

    def set_gid_filter_value(self, gid, _checked=False, block_signal=False):
        index = self.host.gid_filter_combobox.gid_box.findText(str(gid))
        if index < 0:
            index = self.host.gid_filter_combobox.gid_box.findText("-1")
        if index >= 0:
            blocker = None
            if block_signal:
                blocker = QtCore.QSignalBlocker(
                    self.host.gid_filter_combobox.gid_box
                )
            self.host.gid_filter_combobox.gid_box.setCurrentIndex(index)
            del blocker

    def _sync_label_list_visibility(self, get_visible):
        with QtCore.QSignalBlocker(self.host.unique_label_list):
            for row in range(self.host.unique_label_list.count()):
                item = self.host.unique_label_list.item(row)
                visible = self.host.label_info.get(
                    item.data(Qt.ItemDataRole.UserRole), {}
                ).get("visible", True)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if visible
                    else Qt.CheckState.Unchecked
                )
        model = self.host.label_list.model()
        blocker = QtCore.QSignalBlocker(model)
        self.host.label_list.setUpdatesEnabled(False)
        try:
            for item in self.host.label_list:
                is_visible = bool(get_visible(item))
                check_state = (
                    Qt.CheckState.Checked
                    if is_visible
                    else Qt.CheckState.Unchecked
                )
                if item.checkState() != check_state:
                    item.setCheckState(check_state)
                shape = item.shape()
                shape.visible = is_visible
                self.host.canvas.visible[shape] = is_visible
        finally:
            self.host.label_list.setUpdatesEnabled(True)
            del blocker
        self.host.canvas.update()
        self.host._update_select_toggle_button_tooltip()
        if (
            hasattr(self.host, "navigator_dialog")
            and self.host.navigator_dialog.isVisible()
        ):
            self.host.update_navigator_shapes()

    def _refresh_shape_filters(self):
        self.host.update_combo_box(block_signal=True)
        self.host.update_gid_box(block_signal=True)
        current_gid = self.host.gid_filter_combobox.gid_box.currentText()
        if current_gid and current_gid != "-1":
            self.host.gid_selection_changed(
                self.host.gid_filter_combobox.gid_box.currentIndex()
            )
            return
        current_label = self.host.label_filter_combobox.text_box.currentText()
        if current_label:
            self.host.text_selection_changed(
                self.host.label_filter_combobox.text_box.currentIndex()
            )
            return
        self.host.apply_label_visibility()

    def set_label_visibility(self, label, visible):
        if label not in self.host.label_info:
            self.host.label_info[label] = dict(
                delete=False,
                value=None,
                color=list(self.host._get_rgb_by_label(label)),
                opacity=LABEL_OPACITY,
                visible=visible,
            )
        else:
            self.host.label_info[label]["visible"] = visible
        self.host._refresh_shape_filters()

    def apply_label_visibility(self):
        self.host._sync_label_list_visibility(
            lambda item: self.host.label_info.get(item.shape().label, {}).get(
                "visible", True
            )
        )

    def update_combo_box(self, block_signal=False):
        current_label = self.host.label_filter_combobox.text_box.currentText()

        # Get the unique labels and add them to the Combobox.
        labels_list = []
        for item in self.host.label_list:
            label = item.shape().label
            labels_list.append(str(label))
        unique_labels_list = list(set(labels_list))

        # Add a null row for showing all the labels
        unique_labels_list.append("")
        unique_labels_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(
                self.host.label_filter_combobox.text_box
            )
        self.host.label_filter_combobox.update_items(unique_labels_list)
        if current_label in unique_labels_list:
            self.host.set_label_filter_value(
                current_label, block_signal=block_signal
            )
        else:
            self.host.set_label_filter_value("", block_signal=block_signal)
        del blocker

    def update_gid_box(self, block_signal=False):
        current_gid = self.host.gid_filter_combobox.gid_box.currentText()

        # Get the unique group ids and add them to the Combobox.
        gid_list = []
        for item in self.host.label_list:
            gid = item.shape().group_id
            if gid is not None:
                gid_list.append(str(gid))
        unique_gid_list = list(set(gid_list))

        # Add a null row for showing all the labels
        unique_gid_list.append("-1")
        unique_gid_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(self.host.gid_filter_combobox.gid_box)
        self.host.gid_filter_combobox.update_items(unique_gid_list)
        if current_gid in unique_gid_list:
            self.host.set_gid_filter_value(current_gid, block_signal=block_signal)
        else:
            self.host.set_gid_filter_value("-1", block_signal=block_signal)
        del blocker
