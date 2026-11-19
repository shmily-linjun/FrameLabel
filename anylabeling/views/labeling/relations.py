"""Relation (linked object) editing of the labeling view.

Relations are stored in ``other_data['relations']`` and reference
shapes by their ``shape_id``.  Creating, editing, deleting and the
relation dialog are one cohesive rule set that used to live on
``LabelingWidget``.
"""

from uuid import uuid4

from PyQt6 import QtWidgets

from .schema import CHECKED_FIELD
from .widgets.relation_dialog import (
    RelationDialog,
    RelationManagerDialog,
    show_relation_message,
)


class RelationController:
    """Relation list editing and the relation dialogs."""

    def __init__(self, host):
        self.host = host

    def _relation_data_for_shapes(self, shapes):
        other_data = dict(self.host.other_data)
        if "relations" in other_data:
            ids = {shape.get("shape_id") for shape in shapes}
            other_data["relations"] = [
                relation
                for relation in self.host.canvas.relations
                if relation.get("subject_id") in ids
                and relation.get("object_id") in ids
            ]
        return other_data

    def create_relation(self, _checked=False):
        if len(self.host.canvas.selected_shapes) == 2:
            self.host._relation_dialog()

    def edit_relation(self, index):
        if 0 <= index < len(self.host.canvas.relations):
            self.host._relation_dialog(index)

    def delete_selected_relation(self):
        selected = self.host.canvas.selected_relation
        for index, relation in enumerate(self.host.canvas.relations):
            if relation is selected:
                del self.host.canvas.relations[index]
                self.host.canvas.selected_relation = None
                self.host.other_data["relations"] = self.host.canvas.relations
                self.host.other_data[CHECKED_FIELD] = False
                self.host._sync_annotation_checked_state()
                self.host.canvas.update()
                self.host.set_dirty()
                return

    def manage_relations(self, _checked=False):
        dialog = RelationManagerDialog(self.host)

        def preview_selected(index):
            self.host.canvas.preview_relation = (
                self.host.canvas.relations[index]
                if index is not None
                and 0 <= index < len(self.host.canvas.relations)
                else None
            )
            self.host.canvas.update()

        def edit_selected(index):
            self.host.edit_relation(index)
            dialog.refresh(self.host.canvas.shapes, self.host.canvas.relations)

        dialog.preview_requested.connect(preview_selected)
        dialog.edit_requested.connect(edit_selected)
        dialog.refresh(self.host.canvas.shapes, self.host.canvas.relations)
        try:
            dialog.exec()
        finally:
            self.host.canvas.preview_relation = None
            self.host.canvas.update()

    def _relation_dialog(self, index=None):  # noqa: C901
        shapes = [shape for shape in self.host.canvas.shapes if shape.points]
        if len(shapes) < 2:
            self.host._show_relation_message(
                QtWidgets.QMessageBox.Icon.Information,
                self.host.tr("At least two shapes are required."),
            )
            return
        relation = self.host.canvas.relations[index] if index is not None else None
        dialog = RelationDialog(
            shapes, self.host.canvas.selected_shapes, relation, parent=self.host
        )
        while True:
            result = dialog.exec()
            if result == 2:
                del self.host.canvas.relations[index]
                if self.host.canvas.selected_relation is relation:
                    self.host.canvas.selected_relation = None
                break
            if result != QtWidgets.QDialog.DialogCode.Accepted:
                return
            subject_shape, object_shape, text = dialog.values()
            if subject_shape is object_shape or not text:
                self.host._show_relation_message(
                    QtWidgets.QMessageBox.Icon.Warning,
                    self.host.tr(
                        "Choose two different shapes and enter a relation label."
                    ),
                    dialog,
                )
                continue
            for shape in (subject_shape, object_shape):
                if not shape.other_data.get("shape_id"):
                    shape.other_data["shape_id"] = uuid4().hex
                    for backup in self.host.canvas.shapes_backups:
                        for previous in backup:
                            if (
                                previous._relation_identity
                                == shape._relation_identity
                            ):
                                previous.other_data["shape_id"] = (
                                    shape.other_data["shape_id"]
                                )
            updated = {
                "subject_id": subject_shape.other_data["shape_id"],
                "object_id": object_shape.other_data["shape_id"],
                "label": text,
                "score": None,
            }
            if relation is not None:
                if all(
                    updated[key] == relation.get(key)
                    for key in ("subject_id", "object_id", "label")
                ):
                    return
                self.host.canvas.relations[index] = updated
                if self.host.canvas.selected_relation is relation:
                    self.host.canvas.selected_relation = updated
            else:
                self.host.canvas.relations.append(updated)
            break
        self.host.other_data["relations"] = self.host.canvas.relations
        self.host.other_data[CHECKED_FIELD] = False
        self.host._sync_annotation_checked_state()
        self.host.canvas.update()
        self.host.set_dirty()

    def _show_relation_message(self, icon, text, parent=None):
        show_relation_message(icon, text, parent or self.host)

    def on_canvas_shapes_deleted(self, shapes):
        self.host.remove_labels(shapes)
        self.host.set_dirty()
        if self.host.no_shape():
            for action in self.host.actions.on_shapes_present:
                action.setEnabled(False)
