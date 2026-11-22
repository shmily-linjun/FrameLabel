"""Annotation data operations of the labeling view.

Creating/adding shapes, loading a label file's shapes and flags, saving the
current document and keeping the label list/colour bookkeeping in sync are the
core data operations of the labeling window.  They used to be mixed into the
window class together with the UI commands; this module keeps them together so
the data rules can be read (and tested) without the widget layout.

The host (``LabelingWidget``) owns the lists, the canvas, the label dialog and
the file paths; this class is stateless and only reads/mutates the host.
"""

import os
import os.path as osp

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ...services.auto_labeling.types import AutoLabelingMode
from ...services.dataset.codec import ImageAnnotation, KNOWN_TOP_LEVEL_KEYS
from . import utils
from .constants import LABEL_COLORMAP, LABEL_OPACITY
from .label_file import LabelFile, LabelFileError
from .schema import CHECKED_FIELD, IMAGE_TAGS_FIELD
from .settings.schema import load_template_config
from .utils.label_text import format_label_list_text
from .widgets.label_list_widget import (
    LabelListWidgetItem,
    set_item_locked,
)

class AnnotationEditor:
    """Shape/label document operations and colour bookkeeping."""

    def __init__(self, host):
        self.host = host

    def _invalidate_label_manager(self):
        """Refresh the "Classes" tab after the category set changed."""
        panel = getattr(self.host, "label_manager_widget", None)
        if panel is not None:
            panel.invalidate()

    def add_label(self, shape, update_last_label=True, refresh_filters=True):
        if shape.label in self.host.unique_label_list.lock_states:
            shape.locked = self.host.unique_label_list.lock_states[shape.label]
        if shape.group_id is None:
            text = shape.label
        else:
            text = f"{shape.label} ({shape.group_id})"
        label_list_item = LabelListWidgetItem(text, shape)
        new_category = not self.host.unique_label_list.find_items_by_label(
            shape.label
        )
        if new_category:
            item = self.host.unique_label_list.create_item_from_label(shape.label)
            self.host.unique_label_list.addItem(item)
            rgb = self.host._get_rgb_by_label(shape.label)
            self.host.unique_label_list.set_item_label(
                item, shape.label, rgb, LABEL_OPACITY
            )
            self._invalidate_label_manager()

        if shape.label not in self.host.label_info:
            rgb = self.host._get_rgb_by_label(shape.label)
            self.host.label_info[shape.label] = dict(
                delete=False,
                value=None,
                color=list(rgb),
                opacity=LABEL_OPACITY,
                visible=True,
            )

        # Add label to history if it is not a special label
        if shape.label not in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            self.host.label_dialog.add_label_history(
                shape.label, update_last_label=update_last_label
            )
            if update_last_label and shape.group_id is not None:
                self.host.label_dialog._last_gid = shape.group_id

        for action in self.host.actions.on_shapes_present:
            action.setEnabled(True)

        self.host._update_shape_color(shape)
        color = self.host._get_rgb_by_label(shape.label)
        label_list_item.setText(
            format_label_list_text(shape.label, shape.group_id)
        )
        set_item_locked(label_list_item, shape.locked)
        label_list_item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
        self.host.label_list.add_iem(label_list_item)
        if refresh_filters:
            self.host._refresh_shape_filters()

    def load_labels(self, labels, clear_existing=True):
        """
        Load labels to the unique label list widget.

        Args:
            labels (list): List of label names to load
            clear_existing (bool): Whether to clear existing labels before loading new ones
        """
        if not labels:
            return

        if clear_existing:
            self.host.unique_label_list.clear()

        for label in labels:
            # Check if label already exists to avoid duplicates
            if not self.host.unique_label_list.find_items_by_label(label):
                item = self.host.unique_label_list.create_item_from_label(label)
                self.host.unique_label_list.addItem(item)
                rgb = self.host._get_rgb_by_label(label)
                self.host.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

    def _update_shape_color(self, shape):
        r, g, b = self.host._get_rgb_by_label(shape.label)
        shape_config = self.host._config["shape"]
        defaults = load_template_config()["shape"]
        colors = {
            "line_color": (r, g, b, 255),
            "vertex_fill_color": (r, g, b, 255),
            "hvertex_fill_color": (255, 255, 255, 255),
            "fill_color": (r, g, b, 128),
            "select_line_color": (255, 255, 255, 255),
            "select_fill_color": (r, g, b, 155),
        }
        for key, color in colors.items():
            if shape_config[key] != defaults[key]:
                color = shape_config[key]
            setattr(shape, key, QtGui.QColor(*color))

    def _get_rgb_by_label(self, label, skip_label_info=False):
        if label == "AUTOLABEL_ADD":
            return (144, 238, 144)
        if label == "AUTOLABEL_REMOVE":
            return (255, 182, 193)
        if label in self.host.label_info and not skip_label_info:
            return tuple(self.host.label_info[label]["color"])
        if self.host._config["shape_color"] == "auto":
            if not self.host.unique_label_list.find_items_by_label(label):
                item = self.host.unique_label_list.create_item_from_label(label)
                self.host.unique_label_list.addItem(item)
            item = self.host.unique_label_list.find_items_by_label(label)[0]
            label_id = self.host.unique_label_list.indexFromItem(item).row() + 1
            label_id += self.host._runtime_shape_color_shift
            return LABEL_COLORMAP[label_id % len(LABEL_COLORMAP)]
        if (
            self.host._config["shape_color"] == "manual"
            and self.host._config["label_colors"]
            and label in self.host._config["label_colors"]
        ):
            return self.host._config["label_colors"][label]
        if self.host._config["default_shape_color"]:
            return self.host._config["default_shape_color"]
        return (0, 255, 0)

    def remove_labels(self, shapes):
        for shape in shapes:
            item = self.host.label_list.find_item_by_shape(shape)
            self.host.label_list.remove_item(item)
        # Deleting the last object of a category also removes that category
        # from the "Classes" tab, so the table must be re-read.
        self._invalidate_label_manager()
        self.host._refresh_shape_filters()

    def load_shapes(self, shapes, replace=True, update_last_label=True):
        self.host._no_selection_slot = True
        self.host.label_list.setUpdatesEnabled(False)
        try:
            for shape in shapes:
                self.host.add_label(
                    shape,
                    update_last_label=update_last_label,
                    refresh_filters=False,
                )
            self.host.label_list.clearSelection()
        finally:
            self.host.label_list.setUpdatesEnabled(True)
            self.host._no_selection_slot = False
        self.host.canvas.load_shapes(shapes, replace=replace)
        self.host._refresh_shape_filters()

    def load_flags(self, flags):
        self.host.flag_widget.clear()
        for key, flag in flags.items():
            item = QtWidgets.QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if flag else Qt.CheckState.Unchecked
            )
            self.host.flag_widget.addItem(item)

    def save_labels(self, filename):
        label_file = LabelFile()
        # Get current shapes
        # Excluding auto labeling special shapes
        shapes = [
            item.shape().to_dict()
            for item in self.host.label_list
            if item.shape().label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        flags = {}
        for i in range(self.host.flag_widget.count()):
            item = self.host.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.CheckState.Checked
            flags[key] = flag
        self.host.other_data[CHECKED_FIELD] = self.host._annotation_checked()
        signature, allowed = self.host._prepare_attribution(shapes, flags)
        if not allowed:
            return False
        repository = getattr(self.host, "dataset_repository", None)
        if repository is not None:
            return self._save_database_labels(repository, shapes, flags, signature)
        try:
            image_path = osp.relpath(self.host.image_path, osp.dirname(filename))
            image_data = (
                self.host.image_data if self.host._config["store_data"] else None
            )
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))

            label_file.save(
                filename=filename,
                shapes=shapes,
                image_path=image_path,
                image_data=image_data,
                image_height=self.host.image.height(),
                image_width=self.host.image.width(),
                other_data=self.host._relation_data_for_shapes(shapes),
                flags=flags,
            )
            self.host.label_file = label_file
            self.host.operator_gate.baseline = signature
            self.host.actions.save.setIcon(utils.new_icon("save-check"))
            self.host._update_file_row_after_save(len(shapes))
            # The new categories only reach the JSON file now.
            self._invalidate_label_manager()
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.host.error_message(
                self.host.tr("Error saving label data"), self.host.tr("<b>%s</b>") % e
            )
            return False

    def _save_database_labels(self, repository, shapes, flags, signature):
        image_id = getattr(self.host, "dataset_image_id", None)
        if image_id is None:
            self.host.error_message(
                self.host.tr("Error saving label data"),
                self.host.tr("Current image is not registered in the dataset."),
            )
            return False
        other_data = self.host._relation_data_for_shapes(shapes)
        extra = {
            key: value
            for key, value in other_data.items()
            if key not in KNOWN_TOP_LEVEL_KEYS
        }
        annotation = ImageAnnotation(
            shapes=shapes,
            flags=flags,
            tags=list(other_data.get(IMAGE_TAGS_FIELD, []) or []),
            description=other_data.get("description", "") or "",
            split=other_data.get("split"),
            relations=other_data.get("relations", []) or [],
            extra=extra,
            editor=other_data.get("author", "") or "",
            modified_at=other_data.get("modified_at", "") or "",
        )
        try:
            repository.save_annotation(
                image_id,
                annotation,
                editor=other_data.get("author") or None,
                modified_at=other_data.get("modified_at") or None,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator
            self.host.error_message(
                self.host.tr("Error saving label data"),
                self.host.tr("<b>%s</b>") % exc,
            )
            return False
        self.host.operator_gate.baseline = signature
        self.host.actions.save.setIcon(utils.new_icon("save-check"))
        self.host._update_file_row_after_save(len(shapes))
        self.host._refresh_statistics_if_visible()
        # ``save_annotation`` creates the categories in the database; the
        # visible "Classes" tab must re-read them right away.
        self._invalidate_label_manager()
        return True

    def new_shape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        text = None
        manager = getattr(self.host, "label_manager_widget", None)
        if manager is not None:
            text = manager.selected_label()
        if text is None:
            items = self.host.unique_label_list.selectedItems()
            if items:
                text = items[0].data(Qt.ItemDataRole.UserRole)
        flags = {}
        group_id = None
        description = ""
        difficult = False
        kie_linking = []
        review_status = "pending"

        if self.host.canvas.shapes[-1].label in [
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            text = self.host.canvas.shapes[-1].label
        elif (
            self.host._config["display_label_popup"]
            or not text
            or self.host.canvas.shapes[-1].label == AutoLabelingMode.OBJECT
        ):
            last_label = self.host.find_last_label()
            last_gid = (
                self.host.find_last_gid()
                if self.host._config["auto_use_last_gid"]
                else None
            )
            if self.host.digit_to_label is not None:
                text = self.host.digit_to_label
                self.host.digit_to_label = None
                if last_gid is not None:
                    group_id = last_gid
            elif self.host._config["auto_use_last_label"] and last_label:
                text = last_label
                if last_gid is not None:
                    group_id = last_gid
            else:
                previous_text = self.host.label_dialog.edit.text()
                (
                    text,
                    flags,
                    group_id,
                    description,
                    difficult,
                    kie_linking,
                ) = self.host.label_dialog.pop_up(
                    text,
                    group_id=last_gid,
                    move_mode=self.host._config.get("move_mode", "auto"),
                )
                review_status = self.host.label_dialog.get_review_status()
                if not text:
                    self.host.label_dialog.edit.setText(previous_text)

        if text and not self.host.validate_label(text):
            self.host.error_message(
                self.host.tr("Invalid label"),
                self.host.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self.host._config["validate_label"]
                ),
            )
            text = ""
            return

        if self.host.attributes and text:
            text = self.host.reset_attribute(text, self.host.canvas.shapes[-1])

        if text:
            self.host.label_list.clearSelection()
            shape = self.host.canvas.set_last_label(text, flags, group_id)
            shape.group_id = group_id
            shape.description = description
            if text not in [AutoLabelingMode.ADD, AutoLabelingMode.REMOVE]:
                shape.label = text
            shape.difficult = difficult
            shape.kie_linking = kie_linking
            shape.other_data["review_status"] = review_status
            self.host.add_label(shape)
            self.host.actions.edit_mode.setEnabled(True)
            self.host.actions.undo_last_point.setEnabled(False)
            self.host.actions.undo.setEnabled(True)
            self.host.set_dirty()
            if (
                self.host.canvas.drawing()
                and self.host.canvas.create_mode == "polygon"
                and not self.host.actions.create_brush_polygon_mode.isEnabled()
            ):
                self.host.canvas._brush_drawing = True

        else:
            if self.host.canvas.is_magic_wand_mode:
                self.host.canvas.shapes.pop()
                self.host.canvas.shapes_backups.pop()
                self.host.canvas.update()
            else:
                self.host.canvas.undo_last_line()
                self.host.canvas.shapes_backups.pop()
