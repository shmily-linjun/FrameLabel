"""Object list editing, locks and visibility of the labeling view.

The objects tab, the classes tab and the canvas share one set of ``Shape``
instances.  Selecting, renaming, locking, hiding and batch-editing them is a
cohesive set of rules that used to be spread over ``LabelingWidget``.  This
class owns those rules; the widget keeps thin delegates so signals and tests
target the same names as before.

The host (``LabelingWidget``) owns the lists (``label_list``,
``unique_label_list``), the canvas, the class/group ID boxes and the dialog
helpers; this class is stateless and only reads/mutates the host.
"""

import os.path as osp

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from . import utils
from .constants import LABEL_OPACITY
from .pointcloud.icons import get_icon
from .utils.label_text import format_label_list_text
from .utils.theme import get_theme
from .widgets.label_list_widget import (
    LabelListWidgetItem,
    set_item_locked,
)

class ObjectEditor:
    """Selection, label edit, lock and visibility rules for the object list."""

    def __init__(self, host):
        self.host = host

    def _invalidate_label_manager(self):
        """Refresh the "Classes" tab after a category rename/create."""
        panel = getattr(self.host, "label_manager_widget", None)
        if panel is not None:
            panel.invalidate()

    @staticmethod
    def _shape_lock_key(shape):
        return (
            shape.label,
            shape.shape_type,
            shape.group_id,
            tuple((point.x(), point.y()) for point in shape.points),
        )

    def _remember_shape_locks(self):
        if not self.host.image_path:
            return
        states = {}
        for shape in self.host.canvas.shapes:
            states.setdefault(self.host._shape_lock_key(shape), []).append(
                shape.locked
            )
        self.host._session_shape_locks[osp.abspath(self.host.image_path)] = states

    def _restore_shape_locks(self):
        states = self.host._session_shape_locks.get(
            osp.abspath(self.host.image_path), {}
        )
        offsets = {}
        for shape in self.host.canvas.shapes:
            key = self.host._shape_lock_key(shape)
            index = offsets.get(key, 0)
            offsets[key] = index + 1
            if key in states and index < len(states[key]):
                shape.locked = states[key][index]
                item = self.host.label_list.find_item_by_shape(shape)
                if item is not None:
                    item.set_locked(shape.locked)
        self.host.refresh_panel_controls()

    def toggle_select_all(self):
        if self.host.select_toggle_action is None:
            return
        if self.host._has_active_shape_filter():
            self.host._update_select_toggle_button_tooltip()
            return
        if not self.host.canvas.shapes:
            self.host._update_select_toggle_button_tooltip()
            return

        all_visible = self.host._are_all_shapes_visible()
        self.host._set_all_objects_visibility(not all_visible)
        self.host._update_select_toggle_button_tooltip()

    def _has_active_shape_filter(self):
        current_label = self.host.label_filter_combobox.text_box.currentText()
        current_gid = self.host.gid_filter_combobox.gid_box.currentText()
        return bool(current_label) or current_gid not in ["", "-1"]

    def _update_select_toggle_button_tooltip(self):
        self.host.refresh_panel_controls()
        if self.host.select_toggle_action is None:
            return
        if self.host._has_active_shape_filter():
            tooltip = self.host.tr(
                "Toggle shapes visibility is unavailable while a label or group filter is active"
            )
            self.host.select_toggle_action.setEnabled(False)
            self.host.select_toggle_action.setToolTip(tooltip)
            self.host.select_toggle_action.setStatusTip(tooltip)
            return
        self.host.select_toggle_action.setEnabled(bool(self.host.canvas.shapes))
        if self.host._are_all_shapes_visible():
            tooltip = self.host.tr("Hide all shapes")
            icon = utils.new_icon("eye")
        else:
            tooltip = self.host.tr("Show all shapes")
            icon = utils.new_icon("eye-off")
        self.host.select_toggle_action.setIcon(icon)
        self.host.select_toggle_action.setToolTip(tooltip)
        self.host.select_toggle_action.setStatusTip(tooltip)

    def _are_all_shapes_visible(self):
        if len(self.host.label_list) == 0:
            return True
        for item in self.host.label_list:
            if item.checkState() != Qt.CheckState.Checked:
                return False
            shape = item.shape()
            if shape is not None and not shape.visible:
                return False
        return True

    def _set_all_objects_visibility(self, visible):
        """Set all Objects panel checkboxes and shape visibility to visible (True/False)."""
        for item in self.host.label_list:
            label = item.shape().label
            if label in self.host.label_info:
                self.host.label_info[label]["visible"] = visible
        self.host._sync_label_list_visibility(lambda _item: visible)

    def refresh_shape_lock_action(self):
        self.host.refresh_panel_controls()
        items = self.host.label_list.selected_items()
        shapes = [item.shape() for item in items if item.shape() is not None]
        action = self.host.actions.toggle_shape_lock
        action.setEnabled(bool(shapes))
        with QtCore.QSignalBlocker(action):
            action.setChecked(bool(shapes) and all(s.locked for s in shapes))

    def toggle_label_items_lock(self, items):
        shapes = [item.shape() for item in items if item.shape() is not None]
        if not shapes:
            return
        for shape in shapes:
            shape.locked = not shape.locked
        self.host._update_shapes_lock(shapes)

    def refresh_panel_controls(self):
        if not hasattr(self.host, "shapes_visibility_button"):
            return
        theme = get_theme()
        items = [
            self.host.unique_label_list.item(row)
            for row in range(self.host.unique_label_list.count())
        ]
        labels = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        for button, visible in (
            (
                self.host.labels_visibility_button,
                any(
                    self.host.label_info.get(label, {}).get("visible", True)
                    for label in labels
                ),
            ),
            (
                self.host.shapes_visibility_button,
                any(s.visible for s in self.host.canvas.shapes),
            ),
        ):
            button.setIcon(
                get_icon(
                    "eye" if visible else "eye-off",
                    theme["text"],
                    theme["primary"],
                )
            )
        self.host.labels_lock_button.setChecked(
            any(
                self.host.unique_label_list.lock_states.get(label, False)
                for label in labels
            )
        )
        self.host.shapes_lock_button.setChecked(
            any(shape.locked for shape in self.host.canvas.shapes)
        )

        for button in (self.host.labels_lock_button, self.host.shapes_lock_button):
            button.setIcon(
                get_icon(
                    "lock" if button.isChecked() else "unlock",
                    theme["text"],
                    theme["primary"],
                )
            )

    def toggle_all_labels_visibility(self):
        labels = [
            self.host.unique_label_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.host.unique_label_list.count())
        ]
        visible = not any(
            self.host.label_info.get(label, {}).get("visible", True)
            for label in labels
        )
        for label in labels:
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

    def toggle_all_shapes_visibility(self):
        self.host._set_all_objects_visibility(
            not any(s.visible for s in self.host.canvas.shapes)
        )

    def toggle_all_labels_lock(self):
        items = [
            self.host.unique_label_list.item(row)
            for row in range(self.host.unique_label_list.count())
        ]
        states = self.host.unique_label_list.lock_states
        locked = not any(
            states.get(item.data(Qt.ItemDataRole.UserRole), False)
            for item in items
        )
        self.host.toggle_unique_label_items_lock(items, locked=locked)

    def toggle_all_shapes_lock(self):
        shapes = self.host.canvas.shapes
        if not shapes:
            return
        locked = not any(shape.locked for shape in shapes)
        labels = {shape.label for shape in shapes}
        for label in labels:
            self.host.unique_label_list.lock_states.pop(label, None)
            for item in self.host.unique_label_list.find_items_by_label(label):
                self.host.unique_label_list.set_item_locked(item, False)
        self.host._set_shapes_locked(shapes, locked)

    def toggle_unique_label_items_lock(self, items, locked=None):
        states = self.host.unique_label_list.lock_states
        labels = set()
        for item in items:
            label = item.data(Qt.ItemDataRole.UserRole)
            states[label] = (
                not states.get(label, False) if locked is None else locked
            )
            labels.add(label)
            self.host.unique_label_list.set_item_locked(item, states[label])
        for states_by_shape in self.host._session_shape_locks.values():
            for key in list(states_by_shape):
                if key[0] in labels:
                    del states_by_shape[key]
        shapes = [s for s in self.host.canvas.shapes if s.label in labels]
        for shape in shapes:
            shape.locked = states[shape.label]
        if shapes:
            self.host._update_shapes_lock(shapes)
        self.host.refresh_panel_controls()

    def toggle_selected_shapes_lock(self, locked):
        items = self.host.label_list.selected_items()
        shapes = [item.shape() for item in items if item.shape() is not None]
        if not shapes:
            shapes = list(self.host.canvas.selected_shapes)
        if not shapes:
            return
        self.host._set_shapes_locked(shapes, locked)

    def _set_shapes_locked(self, shapes, locked):
        for shape in shapes:
            shape.locked = locked
        self.host._update_shapes_lock(shapes)

    def _update_shapes_lock(self, shapes):
        for shape in shapes:
            item = self.host.label_list.find_item_by_shape(shape)
            if item is not None:
                set_item_locked(item, shape.locked)
        self.host.canvas.store_shapes()
        self.host.canvas.update()
        if self.host.canvas.editing():
            self.host.shape_selection_changed(self.host.canvas.selected_shapes)
        else:
            self.host.refresh_shape_lock_action()

    def validate_label(self, label):
        # no validation
        if self.host._config["validate_label"] is None:
            return True

        for i in range(self.host.unique_label_list.count()):
            label_i = self.host.unique_label_list.item(i).data(
                Qt.ItemDataRole.UserRole
            )
            if self.host._config["validate_label"] in ["exact"]:
                if label_i == label:
                    return True
        return False

    def batch_edit_labels(self, shapes):
        if not self.host._batch_edit_warning_shown:
            reply = QtWidgets.QMessageBox.question(
                self.host,
                self.host.tr("Batch Edit"),
                self.host.tr(
                    "You are about to edit multiple shapes in batch mode. "
                    "This operation cannot be undone.\n\n"
                    "This warning will only be shown once. Do you want to continue?"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )

            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            self.host._batch_edit_warning_shown = True

        first_shape = shapes[0]
        result = self.host.label_dialog.pop_up(
            text=first_shape.label,
            flags=first_shape.flags,
            group_id=first_shape.group_id,
            description=first_shape.description,
            difficult=first_shape.difficult,
            kie_linking=first_shape.kie_linking,
            review_status=first_shape.other_data.get(
                "review_status", "pending"
            ),
            move_mode="center",
        )

        if result[0] is None:
            return

        text, flags, group_id, description, difficult, kie_linking = result

        if not self.host.validate_label(text):
            self.host.error_message(
                self.host.tr("Invalid label"),
                self.host.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self.host._config["validate_label"]
                ),
            )
            return

        for shape in shapes:
            if self.host.attributes and text and text != shape.label:
                text = self.host.reset_attribute(text, shape)

            shape.label = text
            shape.flags = flags
            shape.group_id = group_id
            shape.description = description
            shape.difficult = difficult
            shape.kie_linking = kie_linking
            shape.other_data["review_status"] = (
                self.host.label_dialog.get_review_status()
            )

            self.host._update_shape_color(shape)

            item = self.host.label_list.find_item_by_shape(shape)
            if item is not None:
                if shape.group_id is None:
                    color = self.host._get_rgb_by_label(shape.label)
                    item.setText(
                        format_label_list_text(shape.label, shape.group_id)
                    )
                    item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
                else:
                    item.setText(
                        format_label_list_text(shape.label, shape.group_id)
                    )

        self.host.label_dialog.add_label_history(text)

        if not self.host.unique_label_list.find_items_by_label(text):
            unique_label_item = self.host.unique_label_list.create_item_from_label(
                text
            )
            self.host.unique_label_list.addItem(unique_label_item)
            rgb = self.host._get_rgb_by_label(text)
            self.host.unique_label_list.set_item_label(
                unique_label_item, text, rgb, LABEL_OPACITY
            )

        self.host.set_dirty()
        self.host._refresh_shape_filters()
        self._invalidate_label_manager()

    def edit_label(self, item=None):
        if item and not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem type")

        if not self.host.canvas.editing():
            return

        selected_shapes = self.host.canvas.selected_shapes
        if not selected_shapes:
            return

        if len(selected_shapes) > 1:
            return self.host.batch_edit_labels(selected_shapes)

        if not item:
            item = self.host.current_item()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return
        (
            text,
            flags,
            group_id,
            description,
            difficult,
            kie_linking,
        ) = self.host.label_dialog.pop_up(
            text=shape.label,
            flags=shape.flags,
            group_id=shape.group_id,
            description=shape.description,
            difficult=shape.difficult,
            kie_linking=shape.kie_linking,
            review_status=shape.other_data.get("review_status", "pending"),
            move_mode=self.host._config.get("move_mode", "auto"),
        )
        if text is None:
            return
        if not self.host.validate_label(text):
            self.host.error_message(
                self.host.tr("Invalid label"),
                self.host.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self.host._config["validate_label"]
                ),
            )
            return
        if self.host.attributes and text and text != shape.label:
            text = self.host.reset_attribute(text, shape)
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id
        shape.description = description
        shape.difficult = difficult
        shape.kie_linking = kie_linking
        shape.other_data["review_status"] = (
            self.host.label_dialog.get_review_status()
        )

        # Add to label history
        self.host.label_dialog.add_label_history(shape.label)

        # Update last group_id
        if group_id is not None:
            self.host.label_dialog._last_gid = group_id

        # Update unique label list
        if not self.host.unique_label_list.find_items_by_label(shape.label):
            unique_label_item = self.host.unique_label_list.create_item_from_label(
                shape.label
            )
            self.host.unique_label_list.addItem(unique_label_item)
            rgb = self.host._get_rgb_by_label(shape.label)
            self.host.unique_label_list.set_item_label(
                unique_label_item, shape.label, rgb, LABEL_OPACITY
            )

        self.host._update_shape_color(shape)
        if shape.group_id is None:
            color = self.host._get_rgb_by_label(shape.label)
            item.setText(format_label_list_text(shape.label, shape.group_id))
            item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
        else:
            item.setText(format_label_list_text(shape.label, shape.group_id))
        self.host.set_dirty()
        self.host._refresh_shape_filters()
        self._invalidate_label_manager()

    def shape_selection_changed(self, selected_shapes):
        if selected_shapes and self.host.canvas.selected_relation is not None:
            self.host.canvas.selected_relation = None
            self.host.canvas.update()
        if self.host.canvas.is_brush_mode:
            target = self.host.canvas._brush_target_shape
            if selected_shapes != [target]:
                self.host._no_selection_slot = True
                self.host.label_list.clearSelection()
                item = self.host.label_list.find_item_by_shape(target)
                if item is not None:
                    self.host.label_list.select_item(item)
                    self.host.label_list.scroll_to_item(item)
                self.host._no_selection_slot = False
                return
        self.host._no_selection_slot = True
        for shape in self.host.canvas.selected_shapes:
            shape.selected = False
        self.host.label_list.clearSelection()
        self.host.canvas.selected_shapes = selected_shapes
        allow_merge_shape_type = {"rectangle": 0, "polygon": 0}
        for shape in self.host.canvas.selected_shapes:
            shape.selected = True
            if shape.shape_type in ["rectangle", "polygon"]:
                allow_merge_shape_type[shape.shape_type] += 1
            item = self.host.label_list.find_item_by_shape(shape)
            # NOTE: Handle the case when the shape is not found
            if item is not None:
                self.host.label_list.select_item(item)
                self.host.label_list.scroll_to_item(item)
        self.host._no_selection_slot = False
        n_selected = len(selected_shapes)
        self.host.actions.create_relation.setEnabled(n_selected == 2)
        same_type = (
            len(set(shape.shape_type for shape in selected_shapes)) <= 1
        )
        has_locked = any(shape.locked for shape in selected_shapes)
        has_unlocked = any(not shape.locked for shape in selected_shapes)
        group_shapes = self.host.canvas._active_group_shapes()
        self.host.actions.delete.setEnabled(
            has_unlocked and not (group_shapes and has_locked)
        )
        self.host.actions.duplicate.setEnabled(n_selected)
        self.host.actions.copy.setEnabled(n_selected)
        self.host.actions.edit.setEnabled(n_selected >= 1 and same_type)
        self.host.actions.copy_coordinates.setEnabled(n_selected == 1)
        can_brush_edit = (
            n_selected == 1
            and selected_shapes[0].shape_type == "polygon"
            and not selected_shapes[0].locked
        )
        self.host.actions.edit_brush_mode.setEnabled(can_brush_edit)
        self.host.actions.union_selection.setEnabled(
            not has_locked
            and not all(value > 0 for value in allow_merge_shape_type.values())
            and (
                allow_merge_shape_type["rectangle"] > 1
                or allow_merge_shape_type["polygon"] > 1
            )
        )
        self.host.refresh_shape_lock_action()
        self.host.set_text_editing(True)

    def label_selection_changed(self):
        if self.host._no_selection_slot:
            return
        if self.host.canvas.is_brush_mode:
            return
        if self.host.canvas.editing():
            selected_shapes = []
            for item in self.host.label_list.selected_items():
                selected_shapes.append(item.shape())
            if selected_shapes:
                self.host.canvas.select_shapes(selected_shapes)
            else:
                self.host.canvas.deselect_shape()

    def label_item_changed(self, item):
        shape = item.shape()
        shape.visible = item.checkState() == Qt.CheckState.Checked
        self.host.canvas.set_shape_visible(
            shape, item.checkState() == Qt.CheckState.Checked
        )
        self.host._update_select_toggle_button_tooltip()
        if (
            hasattr(self.host, "navigator_dialog")
            and self.host.navigator_dialog.isVisible()
        ):
            self.host.update_navigator_shapes()
