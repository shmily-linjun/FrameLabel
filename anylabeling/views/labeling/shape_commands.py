"""Object-level editing commands of the labeling view.

Clipboard copy/paste/duplicate, delete, point removal, visibility
toggles, grouping and union of selected shapes all operate on the
canvas selection and the object list.  They used to live on
``LabelingWidget``.
"""

import json
from uuid import uuid4

import cv2
import numpy as np
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

from .logger import logger
from .shape import Shape

# pylupdate6 only records `tr()` calls inside class bodies.  These
# modules also translate text through `host.tr`/`self.tr` in free
# functions and helpers, where the receiver is the LabelingWidget; the
# constant tells `scripts/translation_scan.py` which context to use
# (see docs/dev/CODE_STRUCTURE_REPORT.md).
TR_CONTEXT = "LabelingWidget"


class ShapeCommands:
    """Clipboard, grouping and visibility commands."""

    def __init__(self, host):
        self.host = host

    def undo_shape_edit(self):
        # In brush-edit mode, undo reverts the last brush stroke instead of
        # the global shape history.
        if getattr(self.host.canvas, "is_brush_mode", False):
            self.host.canvas.brush_undo()
            self.host.actions.undo.setEnabled(self.host.canvas.brush_can_undo())
            return
        self.host.canvas.restore_shape()
        self.host.label_list.clear()
        self.host.load_shapes(self.host.canvas.shapes, update_last_label=False)
        self.host.actions.undo.setEnabled(self.host.canvas.is_shape_restorable)
        self.host.set_dirty()
        # Undo may bring back a category that was deleted from the session.
        panel = getattr(self.host, "label_manager_widget", None)
        if panel is not None:
            panel.invalidate()

    def copy_shape_coordinates(self):
        item = self.host.current_item()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return

        points = shape.points
        if shape.shape_type == "rectangle":
            if len(points) >= 2:
                x1, y1 = points[0].x(), points[0].y()
                x2, y2 = points[2].x(), points[2].y()
                coordinates = [x1, y1, x2, y2]
                coordinates = list(map(int, coordinates))
            else:
                return
        else:
            coordinates = []
            for point in points:
                coordinates.extend([point.x(), point.y()])

        coordinates_str = str(coordinates)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(coordinates_str)

    def union_selection(self):
        if any(shape.locked for shape in self.host.canvas.selected_shapes):
            return
        rectangle_shapes, polygon_shapes = [], []
        for shape in self.host.canvas.selected_shapes:
            points = shape.points
            if shape.shape_type == "rectangle":
                xmin, ymin = (points[0].x(), points[0].y())
                xmax, ymax = (points[2].x(), points[2].y())
                rectangle_shapes.append([xmin, ymin, xmax, ymax])
            else:
                polygon_shapes.append([(p.x(), p.y()) for p in points])

        union_shape = shape.copy()
        union_shape.other_data.pop("shape_id", None)
        union_shape._relation_identity = uuid4().hex

        if len(rectangle_shapes) > 0:
            min_x = min([bbox[0] for bbox in rectangle_shapes])
            min_y = min([bbox[1] for bbox in rectangle_shapes])
            max_x = max([bbox[2] for bbox in rectangle_shapes])
            max_y = max([bbox[3] for bbox in rectangle_shapes])

            union_shape.points[0].setX(min_x)
            union_shape.points[0].setY(min_y)
            union_shape.points[1].setX(max_x)
            union_shape.points[1].setY(min_y)
            union_shape.points[2].setX(max_x)
            union_shape.points[2].setY(max_y)
            union_shape.points[3].setX(min_x)
            union_shape.points[3].setY(max_y)
        else:
            # Create a blank mask
            min_x = min([min(p[0] for p in poly) for poly in polygon_shapes])
            min_y = min([min(p[1] for p in poly) for poly in polygon_shapes])
            max_x = max([max(p[0] for p in poly) for poly in polygon_shapes])
            max_y = max([max(p[1] for p in poly) for poly in polygon_shapes])

            width = int(max_x - min_x + 10)
            height = int(max_y - min_y + 10)
            mask = np.zeros((height, width), dtype=np.uint8)

            # Draw all polygons on the mask
            for polygon in polygon_shapes:
                contour = np.array(polygon, dtype=np.int32)
                shifted_contour = contour - np.array(
                    [min_x - 5, min_y - 5], dtype=np.int32
                )
                shifted_contour = shifted_contour.reshape((-1, 1, 2))
                cv2.fillPoly(mask, [shifted_contour], 255)

            # Find contours of the merged shape
            merged_contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if merged_contours:
                largest_contour = max(merged_contours, key=cv2.contourArea)
                epsilon = 0.001 * cv2.arcLength(largest_contour, True)
                approx_contour = cv2.approxPolyDP(
                    largest_contour, epsilon, True
                )
                approx_contour = approx_contour.reshape(-1, 2) + np.array(
                    [min_x - 5, min_y - 5], dtype=np.int32
                )
                union_shape.points = [
                    QtCore.QPointF(float(x), float(y))
                    for x, y in approx_contour
                ]

        # Append merged shape and remove selected shapes
        self.host.add_label(union_shape)
        self.host.remove_labels(self.host.canvas.delete_selected())
        self.host.set_dirty()

        # Update UI state
        if self.host.no_shape():
            for action in self.host.actions.on_shapes_present:
                action.setEnabled(False)

    def duplicate_selected_shape(self):
        added_shapes = self.host.canvas.duplicate_selected_shapes()
        self.host.label_list.clearSelection()
        self.host.label_list.setUpdatesEnabled(False)
        try:
            for shape in added_shapes:
                self.host.add_label(shape, refresh_filters=False)
        finally:
            self.host.label_list.setUpdatesEnabled(True)
        if added_shapes:
            self.host._refresh_shape_filters()
        self.host.set_dirty()

    def paste_selected_shape(self):
        if self.host._config["system_clipboard"]:
            clipboard = QtWidgets.QApplication.clipboard()
            json_str = clipboard.text()
            shapes = []
            try:
                shapeDicts = json.loads(json_str)
                for shapeDict in shapeDicts:
                    shapes.append(Shape().load_from_dict(shapeDict))
            except json.JSONDecodeError as e:
                self.host.error_message(
                    self.host.tr("Error pasting shapes"),
                    self.host.tr("Error decoding shapes: %s") % str(e),
                )
                return
        else:
            shapes = self.host._copied_shapes
        shapes = self.host.canvas.prepare_pasted_shapes(
            shapes, self.host._copied_group_id
        )
        self.host.load_shapes(shapes, replace=False)
        self.host.set_dirty()

    def copy_selected_shape(self):
        group_shapes = self.host.canvas._active_group_shapes()
        self.host._copied_group_id = (
            self.host.canvas._selected_group_id if group_shapes else None
        )
        if self.host._config["system_clipboard"]:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(
                json.dumps([s.to_dict() for s in self.host.canvas.selected_shapes])
            )
        else:
            self.host._copied_shapes = [
                s.copy() for s in self.host.canvas.selected_shapes
            ]
            self.host.actions.paste.setEnabled(len(self.host._copied_shapes) > 0)

    def hide_selected_polygons(self):
        shapes_to_hide = []
        for item in self.host.label_list:
            if item.shape().selected:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.shape().visible = False
                shapes_to_hide.append(item.shape())

        self.host.selected_polygon_stack.extend(shapes_to_hide)
        self.host.canvas.update()
        if (
            hasattr(self.host, "navigator_dialog")
            and self.host.navigator_dialog.isVisible()
        ):
            self.host.update_navigator_shapes()

    def show_hidden_polygons(self):
        if self.host.selected_polygon_stack:
            shape_to_show = self.host.selected_polygon_stack.pop()
            item = self.host.label_list.find_item_by_shape(shape_to_show)
            if item:
                item.setCheckState(Qt.CheckState.Checked)
                shape_to_show.visible = True
                self.host.canvas.update()
                if (
                    hasattr(self.host, "navigator_dialog")
                    and self.host.navigator_dialog.isVisible()
                ):
                    self.host.update_navigator_shapes()
            else:
                logger.warning(
                    f"Shape associated with the hidden item was not found in label list, could not show."
                )

    def toggle_visibility_shapes(self, value):
        for index, item in enumerate(self.host.label_list):
            item.setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            )
            self.host.label_list[index].shape().visible = True if value else False
        self.host._config["show_shapes"] = value
        self.host._update_select_toggle_button_tooltip()
        if (
            hasattr(self.host, "navigator_dialog")
            and self.host.navigator_dialog.isVisible()
        ):
            self.host.update_navigator_shapes()

    def remove_selected_point(self):
        self.host.canvas.remove_selected_point()
        self.host.canvas.update()
        if self.host.canvas.h_shape is not None and not self.host.canvas.h_shape.points:
            self.host.canvas.delete_shape(self.host.canvas.h_shape)
            self.host.remove_labels([self.host.canvas.h_shape])
            self.host.set_dirty()
            if self.host.no_shape():
                for action in self.host.actions.on_shapes_present:
                    action.setEnabled(False)

    def delete_selected_shape(self):
        group_shapes = self.host.canvas._active_group_shapes()
        if group_shapes:
            answer = QtWidgets.QMessageBox.warning(
                self.host,
                self.host.tr("Delete Group"),
                self.host.tr(
                    "Deleting this group will remove %d shapes. "
                    "This action cannot be undone. Do you want to continue?"
                )
                % len(group_shapes),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.host.remove_labels(self.host.canvas.delete_selected())
        self.host.shape_selection_changed(self.host.canvas.selected_shapes)
        self.host.set_dirty()
        if self.host.no_shape():
            for action in self.host.actions.on_shapes_present:
                action.setEnabled(False)

    def shape_text_changed(self):
        description = self.host.shape_text_edit.toPlainText()
        if self.host.canvas.current is not None:
            self.host.canvas.current.description = description
        elif self.host.canvas.editing() and len(self.host.canvas.selected_shapes) == 1:
            self.host.canvas.selected_shapes[0].description = description
        else:
            self.host.other_data["description"] = description
        self.host.set_dirty()

    def set_text_editing(self, enable):
        """Set text editing."""
        if enable:
            # Enable text editing and set shape text from selected shape
            if len(self.host.canvas.selected_shapes) == 1:
                self.host.shape_text_label.setText(self.host.tr("Object Description"))
                with QtCore.QSignalBlocker(self.host.shape_text_edit):
                    self.host.shape_text_edit.setPlainText(
                        self.host.canvas.selected_shapes[0].description or ""
                    )
            else:
                self.host.shape_text_label.setText(self.host.tr("Image Description"))
                with QtCore.QSignalBlocker(self.host.shape_text_edit):
                    self.host.shape_text_edit.setPlainText(
                        self.host.other_data.get("description", "")
                    )
            self.host.shape_text_edit.setDisabled(False)
        else:
            self.host.shape_text_edit.setDisabled(True)
            self.host.shape_text_label.setText(self.host.tr("Description"))
            with QtCore.QSignalBlocker(self.host.shape_text_edit):
                self.host.shape_text_edit.setPlainText("")

    def group_selected_shapes(self):
        self.host.canvas.group_selected_shapes()
        self.host.set_dirty()
        self.host.load_file(self.host.filename)

    def ungroup_selected_shapes(self):
        self.host.canvas.ungroup_selected_shapes()
        self.host.set_dirty()
        self.host.load_file(self.host.filename)
