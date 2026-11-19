"""Apply auto-labeling results to the labeling view.

The auto-labeling panel produces an ``AutoLabelingResult``; this module owns
what happens next: guard against stale results, merge or replace shapes, carry
relations/description/flags/image tags over, and finish the interactive
"object" placeholders.  Keeping it out of ``LabelingWidget`` makes the merge
rules testable without building the whole window.

The host is the labeling widget; the class only calls the widget surface listed
in the methods below (canvas, label list, label dialog, config, save/dirty
helpers).  It holds no state of its own.
"""

import html
import os.path as osp

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from ...services.auto_labeling.types import AutoLabelingMode
from . import utils
from .constants import LABEL_OPACITY
from .logger import logger
from .schema import CHECKED_FIELD, IMAGE_TAGS_FIELD
from .utils.label_text import format_label_list_text


class AutoLabelingHandoff:
    """Turn auto-labeling results into canvas shapes and annotation state."""

    def __init__(self, host):
        self.host = host

    def toggle_auto_labeling_widget(self):
        """Toggle auto labeling widget visibility."""
        if self.host.auto_labeling_widget.isVisible():
            self.host.auto_labeling_widget.hide()
            self.host.actions.run_all_images.setEnabled(False)
        else:
            self.host.auto_labeling_widget.show()
            self.host.actions.run_all_images.setEnabled(True)
        self.host.update_thumbnail_display()

    def new_shapes_from_auto_labeling(self, auto_labeling_result):
        """Apply auto labeling results to the current image."""
        if not self.host.image or not self.host.image_path:
            return

        result_image_path = getattr(auto_labeling_result, "image_path", None)
        if result_image_path and self.host.filename:
            current_filename = osp.normpath(osp.abspath(self.host.filename))
            result_filename = osp.normpath(osp.abspath(result_image_path))
            if result_filename != current_filename:
                logger.warning(
                    "Ignore stale auto labeling result for "
                    f"{result_filename}; current file is {current_filename}"
                )
                return

        result_tags = getattr(auto_labeling_result, "tags", None)
        result_flags = getattr(auto_labeling_result, "flags", None)
        tags_only_result = (
            result_tags is not None
            and result_flags is None
            and not auto_labeling_result.shapes
            and auto_labeling_result.replace is False
            and not auto_labeling_result.description
        )
        annotations_changed = bool(auto_labeling_result.shapes)

        # Clear existing shapes
        if auto_labeling_result.replace:
            locked_shapes = [
                shape for shape in self.host.canvas.shapes if shape.locked
            ]
            annotations_changed |= len(locked_shapes) != len(
                self.host.canvas.shapes
            )
            self.host.label_list.clear()
            self.host.load_shapes(
                locked_shapes + auto_labeling_result.shapes, replace=True
            )
        else:  # Just update existing shapes
            # Remove stale placeholder objects (label AUTOLABEL_OBJECT) from
            # both the object list and the canvas.  Only the list row used to
            # be removed, so the canvas kept an orphan placeholder without a
            # row, and the later "finish object" step crashed on the missing
            # row (AttributeError: 'NoneType' object has no attribute
            # 'setText').
            stale_objects = [
                shape
                for shape in self.host.canvas.shapes
                if shape.label == AutoLabelingMode.OBJECT
            ]
            if stale_objects:
                stale_ids = {id(shape) for shape in stale_objects}
                for shape in stale_objects:
                    item = self.host.label_list.find_item_by_shape(shape)
                    if item is not None:
                        self.host.label_list.remove_item(item)
                self.host.canvas.shapes = [
                    shape
                    for shape in self.host.canvas.shapes
                    if id(shape) not in stale_ids
                ]
            self.host.load_shapes(auto_labeling_result.shapes, replace=False)

        incoming_relations = getattr(auto_labeling_result, "relations", None)
        if auto_labeling_result.replace or incoming_relations is not None:
            shape_ids = {
                s.other_data.get("shape_id") for s in self.host.canvas.shapes
            }
            relations = [
                relation
                for relation in self.host.canvas.relations
                if relation.get("subject_id") in shape_ids
                and relation.get("object_id") in shape_ids
            ]
            if incoming_relations is not None:
                relations.extend(
                    relation
                    for relation in incoming_relations
                    if relation.get("subject_id") in shape_ids
                    and relation.get("object_id") in shape_ids
                )
            if (
                relations != self.host.canvas.relations
                or incoming_relations is not None
            ):
                self.host.canvas.relations = relations
                self.host.other_data["relations"] = relations
                annotations_changed = True
                self.host.canvas.update()

        # Set image description
        if auto_labeling_result.description:
            description = auto_labeling_result.description
            annotations_changed |= description != self.host.other_data.get(
                "description", ""
            )
            self.host.shape_text_label.setText(self.host.tr("Image Description"))
            with QtCore.QSignalBlocker(self.host.shape_text_edit):
                self.host.shape_text_edit.setPlainText(description)
            self.host.other_data["description"] = description
            self.host.shape_text_edit.setDisabled(False)

        if result_flags is not None:
            flags = {
                self.host.flag_widget.item(i).text(): (
                    self.host.flag_widget.item(i).checkState()
                    == Qt.CheckState.Checked
                )
                for i in range(self.host.flag_widget.count())
            }
            annotations_changed |= any(
                key not in flags or flags[key] != value
                for key, value in result_flags.items()
            )
            flags.update(result_flags)
            with QtCore.QSignalBlocker(self.host.flag_widget):
                self.host.load_flags(flags)

        tags_changed = False
        if result_tags is not None:
            tags = utils.normalize_image_tags(
                result_tags, "auto labeling result"
            )
            tags_changed = (
                IMAGE_TAGS_FIELD not in self.host.other_data
                or self.host.other_data[IMAGE_TAGS_FIELD] != tags
            )
            if tags_changed:
                self.host.other_data[IMAGE_TAGS_FIELD] = tags
            self.host.image_tags_widget.set_tags(tags)
            self.host.files.set_row_tags(str(self.host.image_path), tags)

        if annotations_changed or tags_changed:
            self.host.other_data[CHECKED_FIELD] = False
            self.host._sync_annotation_checked_state()

        if tags_changed or not tags_only_result:
            self.host.set_dirty()

    def clear_auto_labeling_marks(self):
        """Clear auto labeling marks from the current image."""
        # Clean up label list
        for shape in self.host.canvas.shapes:
            if shape.label in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]:
                item = self.host.label_list.find_item_by_shape(shape)
                if item is not None:
                    self.host.label_list.remove_item(item)

        # Clean up unique label list
        for shape_label in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            for item in self.host.unique_label_list.find_items_by_label(
                shape_label
            ):
                self.host.unique_label_list.takeItem(
                    self.host.unique_label_list.row(item)
                )

        # Remove shapes from the canvas
        self.host.canvas.shapes = [
            shape
            for shape in self.host.canvas.shapes
            if shape.label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        self.host.canvas.update()

    def find_last_label(self):
        """
        Find the last label in the label list.
        Exclude labels for auto labeling.
        """

        # Get from dialog history
        last_label = self.host.label_dialog.get_last_label()
        if last_label:
            return last_label

        # Get selected label from the label list
        items = self.host.label_list.selected_items()
        if items:
            shape = items[0].data(Qt.ItemDataRole.UserRole)
            return shape.label

        # Get the last label from the label list
        for item in reversed(self.host.label_list):
            shape = item.data(Qt.ItemDataRole.UserRole)
            if shape.label not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]:
                return shape.label

        # No label is found
        return ""

    def find_last_gid(self):
        last_gid = self.host.label_dialog.get_last_gid()
        if last_gid is not None:
            return last_gid

        for item in reversed(self.host.label_list):
            shape = item.data(Qt.ItemDataRole.UserRole)
            if (
                shape.label
                not in [
                    AutoLabelingMode.OBJECT,
                    AutoLabelingMode.ADD,
                    AutoLabelingMode.REMOVE,
                ]
                and shape.group_id is not None
            ):
                return shape.group_id
        return None

    def set_cache_auto_label(self):
        self.host.auto_labeling_widget.on_cache_auto_label_changed(
            self.host.cache_auto_label, self.host.cache_auto_label_group_id
        )

    def finish_auto_labeling_object(self):
        """Finish auto labeling object."""
        has_object, cache_label = False, None
        for shape in self.host.canvas.shapes:
            if shape.label == AutoLabelingMode.OBJECT:
                cache_label = shape.cache_label
                cache_description = shape.cache_description
                has_object = True
                break

        # If there is no object, do nothing
        if not has_object:
            return

        # Ask a label for the object
        review_status = "pending"
        text, flags, group_id, description, difficult, kie_linking = (
            "",
            {},
            None,
            None,
            False,
            [],
        )
        last_label = self.find_last_label()
        last_gid = (
            self.find_last_gid() if self.host._config["auto_use_last_gid"] else None
        )
        if self.host._config["auto_use_last_label"] and last_label:
            text = last_label
            if last_gid is not None:
                group_id = last_gid
        elif cache_label is not None:
            text = cache_label
            description = cache_description
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
                text=self.find_last_label(),
                flags={},
                group_id=last_gid,
                description=None,
                difficult=False,
                kie_linking=[],
                move_mode=self.host._config.get("move_mode", "auto"),
            )
            review_status = self.host.label_dialog.get_review_status()
            if not text:
                self.host.label_dialog.edit.setText(previous_text)
                return

        self.host.cache_auto_label = text
        self.host.cache_auto_label_group_id = group_id
        if not self.host.validate_label(text):
            self.host.error_message(
                self.host.tr("Invalid label"),
                self.host.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self.host._config["validate_label"]
                ),
            )
            return

        if self.host.attributes and text:
            text = self.host.reset_attribute(text, shape)

        # Add to label history
        self.host.label_dialog.add_label_history(text)

        # Update label for the object
        updated_shapes = False
        for shape in self.host.canvas.shapes:
            if shape.label == AutoLabelingMode.OBJECT:
                updated_shapes = True
                shape.label = text
                shape.flags = flags
                shape.group_id = group_id
                shape.description = description
                shape.difficult = difficult
                shape.kie_linking = kie_linking
                shape.other_data["review_status"] = review_status
                # Update unique label list
                if not self.host.unique_label_list.find_items_by_label(shape.label):
                    unique_label_item = (
                        self.host.unique_label_list.create_item_from_label(
                            shape.label
                        )
                    )
                    self.host.unique_label_list.addItem(unique_label_item)
                    rgb = self.host._get_rgb_by_label(shape.label)
                    self.host.unique_label_list.set_item_label(
                        unique_label_item, shape.label, rgb, LABEL_OPACITY
                    )

                # Update label list
                self.host._update_shape_color(shape)
                item = self._auto_labeling_list_item(shape)
                if item is None:
                    continue
                if shape.group_id is None:
                    color = self.host._get_rgb_by_label(shape.label)
                    item.setText(
                        '{} <font color="#{:02x}{:02x}{:02x}">鈼?/font>'.format(
                            html.escape(shape.label), *color
                        )
                    )
                else:
                    item.setText(
                        format_label_list_text(shape.label, shape.group_id)
                    )

        # Clean up auto labeling objects
        self.clear_auto_labeling_marks()

        # Update shape colors
        for shape in self.host.canvas.shapes:
            self.host._update_shape_color(shape)
            color = self.host._get_rgb_by_label(shape.label)
            item = self._auto_labeling_list_item(shape)
            if item is None:
                continue
            item.setText(format_label_list_text(shape.label, shape.group_id))
            item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
            self.host.unique_label_list.update_item_color(
                shape.label, color, LABEL_OPACITY
            )

        if updated_shapes:
            self.host.set_dirty()

    def _auto_labeling_list_item(self, shape):
        """Return the object-list row for ``shape``, creating it if needed.

        Auto-labeling can leave a shape on the canvas that has no row (for
        example after an interrupted marking session).  The "finish object"
        step must not crash on that, so the row is created on demand and
        ``None`` is returned only when it cannot be added at all.
        """
        item = self.host.label_list.find_item_by_shape(shape)
        if item is not None:
            return item
        self.host.add_label(
            shape, update_last_label=False, refresh_filters=False
        )
        return self.host.label_list.find_item_by_shape(shape)

