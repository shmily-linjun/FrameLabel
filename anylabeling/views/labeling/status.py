"""Document status, window title, dirty flag and review state.

The status bar text, the window title, the auto-save trigger and the
``checked`` review state all describe *the document currently open*.  They are
tightly coupled (saving updates all of them) and were previously mixed into
the editing methods.

The host (``LabelingWidget``) owns the canvas/file labels and the QSettings
state; this class is stateless and only reads/mutates the host.
"""

import os.path as osp

from PyQt6 import QtCore
from PyQt6.QtCore import Qt

from ...app_info import __appname__
from . import utils
from .file_list.constants import FILE_COL_NAME
from .schema import CHECKED_FIELD, CHECKED_FIELD_PATTERN


class DocumentStatus:
    """Status bar/title/dirty/review-state handling."""

    def __init__(self, host):
        self.host = host

    def set_dirty(self):
        self.host.actions.save.setIcon(utils.new_icon("save"))
        # Even if we autosave the file, we keep the ability to undo
        self.host.actions.undo.setEnabled(self.host.canvas.is_shape_restorable)

        if self.host._config["auto_save"]:
            label_file = osp.splitext(self.host.image_path)[0] + ".json"
            if self.host.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.host.output_dir + "/" + label_file_without_path
            if not self.host.save_labels(label_file):
                # The save was refused (no operator yet): keep the content
                # marked as unsaved so it is not silently lost.
                self.host.dirty = True
                self.host.actions.save.setEnabled(True)
                self.host.update_progress_title()
                return
            if (
                hasattr(self.host, "navigator_dialog")
                and self.host.navigator_dialog.isVisible()
            ):
                self.host.update_navigator_shapes()
            return
        self.host.dirty = True
        self.host.actions.save.setEnabled(True)
        if (
            hasattr(self.host, "navigator_dialog")
            and self.host.navigator_dialog.isVisible()
        ):
            self.host.update_navigator_shapes()
        self.host.update_progress_title()

    def _document_status_text(self):
        """Cursor position and current filename for the status bar."""
        if self.host.filename is None:
            return ""
        position = getattr(self.host, "_cursor_position", None)
        if position is None:
            coords = "-,-"
        else:
            coords = f"{position[0]},{position[1]}"
        return f"[{coords}|{osp.abspath(str(self.host.filename))}]"

    def _refresh_document_status(self):
        updater = getattr(self.host.parent.parent, "update_document_status", None)
        if updater is not None:
            updater(self.host._document_status_text())

    def _on_canvas_mouse_moved(self, x, y):
        self.host._cursor_position = (
            None if x < 0 or y < 0 else (int(round(x)), int(round(y)))
        )
        self.host._refresh_document_status()

    def _window_title(self):
        if self.host.filename is None:
            return __appname__
        return f"{__appname__} - {self.host._document_status_text()}"

    def update_progress_title(self):
        self.host.parent.parent.setWindowTitle(self.host._window_title())
        self.host._refresh_document_status()

    def set_clean(self):
        self.host.dirty = False
        self.host.actions.save.setEnabled(False)
        self.host.actions.save.setIcon(
            utils.new_icon("save-check" if self.host.label_file else "save")
        )
        self.host.actions.union_selection.setEnabled(False)
        self.host.actions.create_mode.setEnabled(True)
        self.host.actions.create_brush_polygon_mode.setEnabled(True)
        self.host.actions.create_magic_wand_mode.setEnabled(True)
        self.host.actions.create_rectangle_mode.setEnabled(True)
        self.host.actions.create_cuboid_mode.setEnabled(True)
        self.host.actions.create_rotation_mode.setEnabled(True)
        self.host.actions.create_quadrilateral_mode.setEnabled(True)
        self.host.actions.create_circle_mode.setEnabled(True)
        self.host.actions.create_line_mode.setEnabled(True)
        self.host.actions.create_point_mode.setEnabled(True)
        self.host.actions.create_line_strip_mode.setEnabled(True)
        self.host.actions.digit_shortcut_0.setEnabled(True)
        self.host.actions.digit_shortcut_1.setEnabled(True)
        self.host.actions.digit_shortcut_2.setEnabled(True)
        self.host.actions.digit_shortcut_3.setEnabled(True)
        self.host.actions.digit_shortcut_4.setEnabled(True)
        self.host.actions.digit_shortcut_5.setEnabled(True)
        self.host.actions.digit_shortcut_6.setEnabled(True)
        self.host.actions.digit_shortcut_7.setEnabled(True)
        self.host.actions.digit_shortcut_8.setEnabled(True)
        self.host.actions.digit_shortcut_9.setEnabled(True)

        self.host.update_progress_title()

        if self.host.has_label_file():
            self.host.actions.delete_file.setEnabled(True)
        else:
            self.host.actions.delete_file.setEnabled(False)
        self.host._apply_operator_gate()

    def get_image_progress_info(self):
        if self.host.filename and self.host.filename in self.host.fn_to_index:
            current_index = self.host.fn_to_index[str(self.host.filename)]
            total_count = self.host.file_list_widget.count()
            return current_index + 1, total_count
        return 1, 1

    def toggle_actions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for action in self.host.actions.zoom_actions:
            action.setEnabled(value)
        for action in self.host.actions.on_load_active:
            action.setEnabled(value)
        if not value:
            self.host.actions.edit_brush_mode.setEnabled(False)

        if value and self.host.file_list_widget.count() > 0:
            self.host.actions.shape_manager.setEnabled(True)
        else:
            self.host.actions.shape_manager.setEnabled(False)
        self.host.update_browse_actions()
        self.host._apply_operator_gate()

    def update_browse_actions(self):
        index = self.host.fn_to_index.get(str(self.host.filename), -1)
        count = self.host.file_list_widget.count()
        valid = 0 <= index < count
        step = self.host._config["image_jump_step"]
        self.host.actions.jump_next_images.setEnabled(
            valid and index + step < count
        )
        self.host.actions.jump_prev_images.setEnabled(valid and index >= step)
        for action, text, tip in (
            (
                self.host.actions.jump_next_images,
                self.host.tr("Forward %s Images"),
                self.host.tr("Move forward by %s images"),
            ),
            (
                self.host.actions.jump_prev_images,
                self.host.tr("Back %s Images"),
                self.host.tr("Move back by %s images"),
            ),
        ):
            action.setText(text % step)
            action.setIconText((text % step).replace(" ", "\n"))
            action.setToolTip(tip % step)
            action.setStatusTip(tip % step)

    def queue_event(self, function):
        QtCore.QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.host.statusBar().showMessage(message, delay)

    def _label_file_checked(self, label_file):
        if not QtCore.QFile.exists(label_file):
            return False
        try:
            buffer = ""
            with open(label_file, "r", encoding="utf-8") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    buffer = buffer[-32:] + chunk
                    match = CHECKED_FIELD_PATTERN.search(buffer)
                    if match:
                        return (
                            "failed"
                            if match.group(1) == '"failed"'
                            else match.group(1) == "true"
                        )
        except Exception:
            return False
        return False

    def _set_file_item_checked(self, item, checked, shape_count=None):
        if item is None:
            return
        if (
            item.data(Qt.ItemDataRole.UserRole) == checked
            and shape_count is None
        ):
            return
        item.setData(Qt.ItemDataRole.UserRole, checked)
        item.setToolTip(
            f"{item.text()}\n{self.host._annotation_checked_text(checked)}"
        )
        row = self.host.files.row_of(item.text())
        if row is not None:
            self.host.files.apply_row_state(row, checked, shape_count)

    def _file_item_annotation_checked(self, item):
        return item.data(Qt.ItemDataRole.UserRole) in (True, "failed")

    def _create_file_list_item(self, file, label_file=None):
        if label_file is None:
            label_file = self.host.files.label_file_for(file)
        return self.host.files.build_row_cells(file, label_file)[FILE_COL_NAME]

    def _current_file_item(self):
        if str(self.host.filename) not in self.host.fn_to_index:
            return None
        return self.host.file_list_widget.item(self.host.fn_to_index[str(self.host.filename)])

    def _annotation_checked(self):
        checked = self.host.other_data.get(CHECKED_FIELD, False)
        return "failed" if checked == "failed" else checked is True

    def _annotation_checked_text(self, checked=None):
        if checked is None:
            checked = self.host._annotation_checked()
        return {
            False: self.host.tr("Unchecked"),
            True: self.host.tr("Check Passed"),
            "failed": self.host.tr("Check Failed"),
        }[checked]

    def _update_annotation_checked_action(self):
        if not hasattr(self.host, "actions"):
            return
        checked = self.host._annotation_checked()
        for action, status in (
            (self.host.actions.clear_annotation_checked, False),
            (self.host.actions.toggle_annotation_checked, True),
            (self.host.actions.fail_annotation_checked, "failed"),
        ):
            action.setChecked(checked == status)

    def _update_file_row_after_save(self, shape_count):
        path = str(self.host.image_path)
        item = self.host.files.item_by_path(path)
        if item is None:
            return
        item.setCheckState(Qt.CheckState.Checked)
        self.host._set_file_item_checked(
            item, self.host._annotation_checked(), shape_count
        )

    def _update_current_file_checked_item(self):
        item = self.host._current_file_item()
        if item is not None:
            self.host._set_file_item_checked(
                item, self.host._annotation_checked(), len(self.host.canvas.shapes)
            )

    def _sync_annotation_checked_state(self):
        self.host.canvas_adjustment.set_status(self.host._annotation_checked())
        self.host._update_annotation_checked_action()
        self.host._update_current_file_checked_item()
        self.host.update_progress_title()

    def set_annotation_checked(self, checked):
        if self.host.filename is None or self.host.image.isNull():
            return
        self.host.other_data[CHECKED_FIELD] = (
            "failed" if checked == "failed" else bool(checked)
        )
        self.host._sync_annotation_checked_state()
        label_file = self.host.get_label_file()
        if self.host.save_labels(label_file):
            self.host.set_clean()
