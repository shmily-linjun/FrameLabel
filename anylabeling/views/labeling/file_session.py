"""Opening, navigating, saving and deleting label files.

The labeling window works on one image at a time, but most of its commands are
file operations: open a file/folder, move to the next or previous image, save,
close, delete and import extra files.  These rules used to live on
``LabelingWidget`` next to the annotation editing code; keeping them here makes
the file lifecycle readable on its own.

The host (``LabelingWidget``) owns the state (``filename``, ``image_path``,
``label_file``, ``dirty``, the file table controller and the action registry);
this class is stateless and only reads/mutates the host.
"""

import os
import os.path as osp
import re
import shutil

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ...app_info import __appname__
from . import utils
from .label_file import LabelFile, LabelFileError
from .logger import logger
from .schema import CHECKED_FIELD, IMAGE_TAGS_FIELD
from .utils.file_search import filter_image_files, parse_search_query
from .widgets.file_dialog_preview import FileDialogPreview

class FileSession:
    """File lifecycle commands of the labeling window."""

    def __init__(self, host):
        self.host = host

    def load_file(self, filename=None):  # noqa: C901
        """Load the specified file, or the last opened file if None."""

        self.host._cursor_position = None

        # NOTE(jack): Does we need to save the config here?
        # save_config(self._config)

        # For auto labeling, clear the previous marks
        # and inform the next files to be annotated
        # NOTE(jack): this is not needed for now
        # self.clear_auto_labeling_marks()
        # self.inform_next_files(filename)

        # Changing file_list_widget loads file
        if str(filename) in self.host.fn_to_index and (
            self.host.file_list_widget.currentRow()
            != self.host.fn_to_index[str(filename)]
        ):
            self.host.file_list_widget.setCurrentRow(
                self.host.fn_to_index[str(filename)]
            )
            self.host.file_list_widget.update()
            return False

        self.host.reset_state()
        self.host.canvas.setEnabled(False)

        if filename is None:
            filename = self.host.settings.value("filename", "")
        filename = str(filename)
        if not QtCore.QFile.exists(filename):
            self.host.error_message(
                self.host.tr("Error opening file"),
                self.host.tr("No such file: <b>%s</b>") % filename,
            )
            return False

        # assumes same name, but json extension
        label_file = osp.splitext(filename)[0] + ".json"
        image_dir = None
        if self.host.output_dir:
            image_dir = osp.dirname(filename)
            label_file_without_path = osp.basename(label_file)
            label_file = self.host.output_dir + "/" + label_file_without_path

        if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
            label_file
        ):
            try:
                self.host.label_file = LabelFile(
                    label_file,
                    image_dir,
                    image_path=(
                        None if LabelFile.is_label_file(filename) else filename
                    ),
                )
            except LabelFileError as e:
                self.host.error_message(
                    self.host.tr("Error opening file"),
                    self.host.tr(
                        "<p><b>%s</b></p>"
                        "<p>Make sure <i>%s</i> is a valid label file."
                    )
                    % (e, label_file),
                )
                self.host.status(self.host.tr("Error reading %s") % label_file)
                return False
            self.host.image_data = self.host.label_file.image_data
            self.host.image_path = self.host.label_file.resolved_image_path
            self.host.other_data = self.host.label_file.other_data
            self.host.other_data[CHECKED_FIELD] = self.host._annotation_checked()
            with QtCore.QSignalBlocker(self.host.shape_text_edit):
                self.host.shape_text_edit.setPlainText(
                    self.host.other_data.get("description", "")
                )
        else:
            self.host.image_data = LabelFile.load_image_file(filename)
            if self.host.image_data:
                self.host.image_path = filename
            self.host.label_file = None
            self.host.other_data = {CHECKED_FIELD: False}
            with QtCore.QSignalBlocker(self.host.shape_text_edit):
                self.host.shape_text_edit.setPlainText("")
        self.host.shape_text_label.setText(self.host.tr("Image Description"))
        self.host.shape_text_edit.setDisabled(False)
        self.host.canvas.relations = self.host.other_data.get("relations", [])
        self.host.operator_gate.baseline = None

        # TODO(jack): icc profile issue warning
        # - qt.gui.icc: fromIccProfile: failed minimal tag size sanity
        # - qt.gui.icc: fromIccProfile: invalid tag offset alignment
        image = utils.img_data_to_qimage(self.host.image_data, filename)

        if image.isNull():
            formats = [
                f"*{ext}" for ext in utils.get_supported_image_extensions()
            ]
            self.host.error_message(
                self.host.tr("Error opening file"),
                self.host.tr(
                    "<p>Make sure <i>{0}</i> is a valid image file.<br/>"
                    "Supported image formats: {1}</p>"
                ).format(filename, ",".join(formats)),
            )
            self.host.status(self.host.tr("Error reading %s") % filename)
            return False
        self.host.image = image
        self.host.filename = filename
        self.host.image_tags_widget.set_tags(
            self.host.other_data.get(IMAGE_TAGS_FIELD, [])
        )
        self.host.image_tags_widget.set_interactions_enabled(
            self.host._operator_edit_allowed()
        )

        if (
            hasattr(self.host, "navigator_dialog")
            and self.host.navigator_dialog.isVisible()
        ):
            self.host.navigator_dialog.set_image(QtGui.QPixmap.fromImage(image))
            self.host.update_navigator_shapes()
        if (
            hasattr(self.host, "_should_restore_navigator")
            and self.host._should_restore_navigator
        ):
            self.host._should_restore_navigator = False
            if self.host.navigator_dialog.isVisible():
                self.host.update_navigator_viewport()
        if self.host._config["keep_prev"]:
            prev_shapes = self.host.canvas.shapes
        self.host.canvas.load_pixmap(QtGui.QPixmap.fromImage(image))

        # load label flags
        flags = {k: False for k in self.host.image_flags or []}
        if self.host.label_file:
            for shape in self.host.label_file.shapes:
                default_flags = {}
                if self.host._config["label_flags"]:
                    for pattern, keys in self.host._config["label_flags"].items():
                        if re.match(pattern, shape.label):
                            for key in keys:
                                default_flags[key] = False
                    shape.flags = {
                        **default_flags,
                        **shape.flags,
                    }
            self.host.load_shapes(self.host.label_file.shapes, update_last_label=False)
            self.host._restore_shape_locks()
            self.host.image_tags_widget.refresh_colors()
            if self.host.label_file.flags is not None:
                flags.update(self.host.label_file.flags)
        self.host.load_flags(flags)

        # load shapes
        if self.host._config["keep_prev"] and self.host.no_shape():
            # Carrying shapes over from the previous image is not an operator
            # edit: keep the attribution of the loaded file untouched.
            self.host.operator_gate.suppress = True
            try:
                self.host.load_shapes(
                    prev_shapes, replace=False, update_last_label=False
                )
                self.host.set_dirty()
            finally:
                self.host.operator_gate.suppress = False
        else:
            self.host.set_clean()
        self.host.operator_gate.baseline = self.host._content_signature_now()
        self.host._refresh_attribution_display()
        self.host.canvas.setEnabled(True)

        saved_pan = QtCore.QPointF(
            self.host.pan_values.get(self.host.filename, QtCore.QPointF())
        )
        saved_scroll = {
            orientation: values[self.host.filename]
            for orientation, values in self.host.scroll_values.items()
            if self.host.filename in values
        }
        # set zoom values
        is_initial_load = not self.host.zoom_values
        if self.host.filename in self.host.zoom_values:
            self.host.zoom_mode = self.host.zoom_values[self.host.filename][0]
            self.host.set_zoom(self.host.zoom_values[self.host.filename][1])
        elif is_initial_load or not self.host._config["keep_prev_scale"]:
            self.host.adjust_scale(initial=True)
        # set scroll values
        for orientation, value in saved_scroll.items():
            self.host.set_scroll(orientation, value)
        self.host.canvas.pan_offset = saved_pan
        self.host.pan_values[self.host.filename] = QtCore.QPointF(saved_pan)
        self.host.constrain_canvas_pan()

        if (
            not self.host.canvas_adjustment.opacity_pin.isChecked()
            and self.host.recent_files
            and self.host.recent_files[0] != self.host.filename
        ):
            self.host.canvas_adjustment.opacity_slider.setValue(
                self.host.canvas_adjustment.OPACITY_DEFAULT
            )

        # set brightness contrast values
        brightness, contrast = self.host.brightness_contrast_values.get(
            self.host.filename, (None, None)
        )
        if self.host._config["keep_prev_brightness"] and self.host.recent_files:
            brightness, _ = self.host.brightness_contrast_values.get(
                self.host.recent_files[0], (None, None)
            )
        if self.host._config["keep_prev_contrast"] and self.host.recent_files:
            _, contrast = self.host.brightness_contrast_values.get(
                self.host.recent_files[0], (None, None)
            )
        self.host.brightness_contrast_values[self.host.filename] = (brightness, contrast)
        # Always refresh the source image used by the inline adjustment panel.
        self.host.brightness_contrast_processor.update_image(
            utils.img_data_to_pil(self.host.image_data)
        )
        if brightness is not None or contrast is not None:
            qimage = self.host.brightness_contrast_processor.adjust(
                brightness if brightness is not None else 50,
                contrast if contrast is not None else 50,
            )
            self.host.canvas.load_pixmap(
                QtGui.QPixmap.fromImage(qimage), clear_shapes=False
            )
        # Sync the inline adjustment sliders (50 is the neutral value).
        self.host.canvas_adjustment.set_brightness_contrast(
            brightness if brightness is not None else 50,
            contrast if contrast is not None else 50,
        )

        self.host.paint_canvas()
        self.host.add_recent_file(self.host.filename)
        self.host.toggle_actions(True)
        self.host.canvas.setFocus()
        self.host._sync_annotation_checked_state()
        self.host.update_thumbnail_display()

        # Reveal the adjustment panel now that an image is loaded.
        self.host.canvas_adjustment.show()
        self.host._position_canvas_adjustment()

        if self.host.compare_view_manager.is_active():
            self.host.compare_view_manager.load_compare_for_file(self.host.filename)

        return True

    def load_recent(self, filename):
        if self.host.may_continue():
            self.host.load_file(filename)

    def load_recent_dir(self, dirpath):
        self.host.import_image_folder(dirpath)

    def open_prev_unchecked_image(self):
        if (
            not self.host.may_continue()
            or len(self.host.image_list) <= 0
            or self.host.filename is None
        ):
            return

        current_index = self.host.fn_to_index[str(self.host.filename)]
        for i in range(current_index - 1, -1, -1):
            if not self.host._file_item_annotation_checked(
                self.host.file_list_widget.item(i)
            ):
                filename = self.host.image_list[i]
                if filename:
                    self.host.load_file(filename)
                break

    def open_next_unchecked_image(self, _value=False):
        if (
            not self.host.may_continue()
            or len(self.host.image_list) <= 0
            or self.host.filename is None
        ):
            return

        current_index = self.host.fn_to_index[str(self.host.filename)]
        for i in range(current_index + 1, len(self.host.image_list)):
            if not self.host._file_item_annotation_checked(
                self.host.file_list_widget.item(i)
            ):
                filename = self.host.image_list[i]
                if filename:
                    self.host.load_file(filename)
                break

    def open_prev_image(self, _value=False):
        if not self.host.may_continue():
            return
        if self.host.file_list_widget.count() <= 0:
            return
        if self.host.filename is None:
            return
        current_index = self.host.fn_to_index[str(self.host.filename)]
        if current_index - 1 >= 0:
            filename = self.host._file_path_at(current_index - 1)
            if filename:
                self.host.load_file(filename)

    def open_next_image(self, _value=False, load=True):
        if not self.host.may_continue():
            return
        count = self.host.file_list_widget.count()
        if count <= 0:
            return
        filename = None
        if self.host.filename is None:
            filename = self.host._file_path_at(0)
        else:
            current_index = self.host.fn_to_index[str(self.host.filename)]
            if current_index + 1 < count:
                filename = self.host._file_path_at(current_index + 1)
            else:
                filename = self.host._file_path_at(count - 1)
        self.host.filename = filename
        if self.host.filename and load:
            self.host.load_file(self.host.filename)

    def open_file(self, _value=False):
        if not self.host.may_continue():
            return
        path = osp.dirname(str(self.host.filename)) if self.host.filename else "."
        formats = [f"*{ext}" for ext in utils.get_supported_image_extensions()]
        filters = self.host.tr("Image & Label files (%s)") % " ".join(
            formats + [f"*{LabelFile.suffix}"]
        )
        file_dialog = FileDialogPreview(self.host)
        file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter(filters)
        file_dialog.setWindowTitle(
            self.host.tr("%s - Choose Image or Label file") % __appname__,
        )
        file_dialog.setWindowFilePath(path)
        file_dialog.setViewMode(QtWidgets.QFileDialog.ViewMode.Detail)
        if file_dialog.exec():
            filename = file_dialog.selectedFiles()[0]
            if filename:
                self.host._clear_file_list()
                self.host.load_file(filename)

    def change_output_dir_dialog(self, _value=False):
        default_output_dir = self.host.output_dir
        if default_output_dir is None and self.host.filename:
            default_output_dir = osp.dirname(self.host.filename)
        if default_output_dir is None:
            default_output_dir = self.host.current_path()

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self.host,
            self.host.tr("%s - Save/Load Annotations in Directory") % __appname__,
            default_output_dir,
            QtWidgets.QFileDialog.Option.ShowDirsOnly
            | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
        )
        output_dir = str(output_dir)

        if not output_dir:
            return

        self.host.output_dir = output_dir

        self.host.statusBar().showMessage(
            self.host.tr("%s . Annotations will be saved/loaded in %s")
            % ("Change Annotations Dir", self.host.output_dir)
        )
        self.host.statusBar().show()

        current_filename = self.host.filename
        self.host.import_image_folder(self.host.last_open_dir, load=False)

        if current_filename in self.host.image_list:
            # retain currently selected file
            self.host.file_list_widget.setCurrentRow(
                self.host.fn_to_index[str(current_filename)]
            )
            self.host.file_list_widget.repaint()

    def save_file(self, _value=False):
        assert not self.host.image.isNull(), "cannot save empty image"
        if self.host.label_file:
            # DL20180323 - overwrite when in directory
            self.host._save_file(self.host.label_file.filename)
        elif self.host.output_file:
            self.host._save_file(self.host.output_file)
            self.host.close()
        else:
            self.host._save_file(self.host.save_file_dialog())

    def save_file_as(self, _value=False):
        assert not self.host.image.isNull(), "cannot save empty image"
        self.host._save_file(self.host.save_file_dialog())

    def save_file_dialog(self):
        caption = self.host.tr("%s - Choose File") % __appname__
        filters = self.host.tr("Label files (*%s)") % LabelFile.suffix
        if self.host.output_dir:
            file_dialog = QtWidgets.QFileDialog(
                self.host, caption, self.host.output_dir, filters
            )
        else:
            file_dialog = QtWidgets.QFileDialog(
                self.host, caption, self.host.current_path(), filters
            )
        file_dialog.setDefaultSuffix(LabelFile.suffix[1:])
        file_dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setOption(
            QtWidgets.QFileDialog.Option.DontConfirmOverwrite, False
        )
        file_dialog.setOption(
            QtWidgets.QFileDialog.Option.DontUseNativeDialog, False
        )
        basename = osp.basename(osp.splitext(self.host.filename)[0])
        if self.host.output_dir:
            default_labelfile_name = osp.join(
                self.host.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.host.current_path(), basename + LabelFile.suffix
            )
        filename = file_dialog.getSaveFileName(
            self.host,
            self.host.tr("Choose File"),
            default_labelfile_name,
            self.host.tr("Label files (*%s)") % LabelFile.suffix,
        )
        if isinstance(filename, tuple):
            filename, _ = filename
        return filename

    def _save_file(self, filename):
        if filename and self.host.save_labels(filename):
            self.host.add_recent_file(filename)
            self.host.set_clean()

    def close_file(self, _value=False):
        if not self.host.may_continue():
            return
        self.host.reset_state()
        self.host.set_clean()
        self.host.toggle_actions(False)
        self.host.canvas.setEnabled(False)
        self.host.actions.save_as.setEnabled(False)

    def get_label_file(self):
        if self.host.label_file:
            return self.host.label_file.filename
        base = self.host.image_path if self.host.image_path else self.host.filename
        if base.lower().endswith(".json"):
            return base
        lf = osp.splitext(base)[0] + ".json"
        if self.host.output_dir:
            lf = osp.join(self.host.output_dir, osp.basename(lf))
        return lf

    def get_image_file(self):
        if not self.host.filename.lower().endswith(".json"):
            image_file = self.host.filename
        else:
            image_file = self.host.image_path

        return image_file

    def delete_file(self):
        mb = QtWidgets.QMessageBox
        if self.host._config.get("keep_prev", False):
            mb.warning(
                self.host,
                self.host.tr("Attention"),
                self.host.tr(
                    "Please disable 'Keep Previous Annotation' before deleting the label file."
                ),
                mb.StandardButton.Ok,
            )
            return

        msg = self.host.tr(
            "You are about to permanently delete this label file, "
            "proceed anyway?"
        )
        answer = mb.warning(
            self.host,
            self.host.tr("Attention"),
            msg,
            mb.StandardButton.Yes | mb.StandardButton.No,
        )
        if answer != mb.StandardButton.Yes:
            return

        label_file = self.host.get_label_file()
        if osp.exists(label_file):
            os.remove(label_file)
            logger.info(f"Label file is removed: {label_file}")

            item = self.host.file_list_widget.currentItem()
            item.setCheckState(Qt.CheckState.Unchecked)
            self.host._set_file_item_checked(item, False)

            filename = self.host.filename
            self.host.reset_state()
            self.host.filename = filename
            if self.host.filename:
                self.host.load_file(self.host.filename)

    def delete_image_file(self):
        if len(self.host.image_list) < 2:
            return

        mb = QtWidgets.QMessageBox
        if self.host._config.get("keep_prev", False):
            mb.warning(
                self.host,
                self.host.tr("Attention"),
                self.host.tr(
                    "Please disable 'Keep Previous Annotation' before deleting the image file."
                ),
                mb.StandardButton.Ok,
            )
            return

        msg = self.host.tr(
            "You are about to permanently delete this image file, "
            "proceed anyway?"
        )
        answer = mb.warning(
            self.host,
            self.host.tr("Attention"),
            msg,
            mb.StandardButton.Yes | mb.StandardButton.No,
        )
        if answer != mb.StandardButton.Yes:
            return

        image_file = self.host.get_image_file()
        if osp.exists(image_file):
            image_path, image_name = osp.split(image_file)
            save_path = osp.join(image_path, "..", "_delete_")
            os.makedirs(save_path, exist_ok=True)
            save_file = osp.join(save_path, image_name)
            shutil.move(image_file, save_file)
            logger.info(f"Image file is moved to: {osp.realpath(save_file)}")

            label_dir_path = osp.dirname(self.host.filename)
            if self.host.output_dir:
                label_dir_path = self.host.output_dir
            label_name = osp.splitext(image_name)[0] + ".json"
            label_file = osp.join(label_dir_path, label_name)
            if not osp.exists(label_file):
                label_file = osp.join(osp.dirname(image_file), label_name)
            if osp.exists(label_file):
                os.remove(label_file)
                logger.info(f"Label file is removed: {image_file}")

            filename = None
            if self.host.filename is None:
                filename = self.host.image_list[0]
            else:
                current_index = self.host.fn_to_index[str(self.host.filename)]
                if current_index + 1 < len(self.host.image_list):
                    filename = self.host.image_list[current_index + 1]
                else:
                    filename = self.host.image_list[0]

            self.host.reset_state()
            if osp.isfile(image_path):
                image_path = osp.dirname(image_path)
            self.host.import_image_folder(image_path)

            self.host.filename = filename
            if self.host.filename:
                self.host.load_file(self.host.filename)

    def has_labels(self):
        if self.host.no_shape():
            self.host.error_message(
                "No objects labeled",
                "You must label at least one object to save the file.",
            )
            return False
        return True

    def has_label_file(self):
        if self.host.filename is None:
            return False

        label_file = self.host.get_label_file()
        return osp.exists(label_file)

    def may_continue(self):
        self.host.image_tags_widget.finish_for_image_change()
        if not self.host.dirty:
            return True
        mb = QtWidgets.QMessageBox
        msg = self.host.tr(
            f'Save annotations to "{self.host.filename!r}" before closing?'
        )
        answer = mb.question(
            self.host,
            self.host.tr("Save annotations?"),
            msg,
            mb.StandardButton.Save
            | mb.StandardButton.Discard
            | mb.StandardButton.Cancel,
            mb.StandardButton.Save,
        )
        if answer == mb.StandardButton.Discard:
            return True
        if answer == mb.StandardButton.Save:
            self.host.save_file()
            return not self.host.dirty
        # answer == mb.Cancel
        return False

    def error_message(self, title, message):
        return QtWidgets.QMessageBox.critical(
            self.host, title, f"<p><b>{title}</b></p>{message}"
        )

    def current_path(self):
        return osp.dirname(str(self.host.filename)) if self.host.filename else "."

    def import_files_dialog(self):
        if not self.host.may_continue():
            return
        default_dir = self.host.last_open_dir
        if not default_dir:
            default_dir = (
                osp.dirname(str(self.host.filename)) if self.host.filename else "."
            )
        formats = [
            f"*{ext}" for ext in utils.get_supported_image_extensions()
        ]
        files, _selected_filter = QtWidgets.QFileDialog.getOpenFileNames(
            self.host,
            self.host.tr("%s - Import Files") % __appname__,
            default_dir,
            self.host.tr("Image files (%s)") % " ".join(formats),
        )
        files = [str(file) for file in files if file]
        if files:
            self.host.import_dropped_image_files(files)

    def open_folder_dialog(self, _value=False, dirpath=None):
        if not self.host.may_continue():
            return

        default_open_dir_path = dirpath if dirpath else "."
        if self.host.last_open_dir and osp.exists(self.host.last_open_dir):
            default_open_dir_path = self.host.last_open_dir
        else:
            default_open_dir_path = (
                osp.dirname(self.host.filename) if self.host.filename else "."
            )

        target_dir_path = str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self.host,
                self.host.tr("%s - Open Directory") % __appname__,
                default_open_dir_path,
                QtWidgets.QFileDialog.Option.ShowDirsOnly
                | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
            )
        )
        self.host.import_image_folder(target_dir_path)

    @property
    def image_list(self):
        return [
            self.host._file_path_at(row)
            for row in range(self.host.file_list_widget.rowCount())
        ]

    def import_dropped_image_files(self, image_files):
        extensions = utils.get_supported_image_extensions()

        self.host.filename = None
        valid_files = []
        rows = []
        for file in image_files:
            if file in self.host.image_list or not file.lower().endswith(
                tuple(extensions)
            ):
                continue
            valid_files.append(file)
            label_file = osp.splitext(file)[0] + ".json"
            if self.host.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.host.output_dir + "/" + label_file_without_path
            rows.append((file, label_file))

        self.host.files.update_import_times(valid_files)
        for file, label_file in rows:
            self.host.files.append_row(file, label_file)
        self.host.file_list_widget.fill_name_column()

        if len(self.host.image_list) > 1:
            self.host.actions.open_next_image.setEnabled(True)
            self.host.actions.open_prev_image.setEnabled(True)
            self.host.actions.open_next_unchecked_image.setEnabled(True)
            self.host.actions.open_prev_unchecked_image.setEnabled(True)

        self.host.toggle_actions(True)
        self.host.open_next_image()

        if valid_files and self.host._config.get("exif_scan_enabled", True):
            self.host.async_exif_scanner.start_scan(valid_files)

    def import_image_folder(self, dirpath, pattern=None, load=True):
        if not self.host.may_continue() or not dirpath:
            return

        if self.host.compare_view_manager.is_active():
            self.host.close_compare_view(confirm=False)

        self.host.last_open_dir = dirpath
        self.host.filename = None
        self.host.update_browse_actions()
        self.host._clear_file_list()

        files_on_disk = list(utils.scan_all_images(dirpath))
        if pattern:
            query = parse_search_query(pattern)
            image_files = filter_image_files(
                files_on_disk, query, self.host.output_dir
            )
        else:
            image_files = files_on_disk

        self.host.files.update_import_times(image_files)
        for filename in image_files:
            label_file = osp.splitext(filename)[0] + ".json"
            if self.host.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.host.output_dir + "/" + label_file_without_path
            self.host.files.append_row(filename, label_file)
        self.host.file_list_widget.fill_name_column()

        self.host.actions.open_next_image.setEnabled(True)
        self.host.actions.open_prev_image.setEnabled(True)
        self.host.actions.open_next_unchecked_image.setEnabled(True)
        self.host.actions.open_prev_unchecked_image.setEnabled(True)
        self.host.toggle_actions(True)
        self.host.open_next_image(load=load)

        if image_files and self.host._config.get("exif_scan_enabled", True):
            self.host.async_exif_scanner.start_scan(image_files)
        self.host._refresh_statistics_if_visible()
