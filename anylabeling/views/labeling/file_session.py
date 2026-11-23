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
from datetime import datetime
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ...app_info import __appname__
from . import utils
from .label_file import LabelFile, LabelFileError
from .logger import logger
from .schema import CHECKED_FIELD, IMAGE_TAGS_FIELD
from .shape import Shape
from .utils.file_meta import FileMeta, SPLIT_KEYS
from .utils.file_search import (
    filter_image_files,
    matches_query_label_data,
    parse_search_query,
)


def _unescape_filter_value(value):
    """Remove one level of backslash escaping from a raw filter value."""
    result = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            result.append(value[index + 1])
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)
from .widgets.file_dialog_preview import FileDialogPreview


class DatabaseLabelFile:
    """Minimal LabelFile-shaped holder for an annotation loaded from SQLite.

    ``FileSession.load_file`` and the rest of the view expect a label file
    object with ``shapes``/``flags``/``other_data``/``image_data``.  In database
    mode there is no JSON file, so this object carries the same fields and uses
    the image path as its save identity.
    """

    suffix = ".db"

    def __init__(
        self,
        filename,
        image_data,
        resolved_image_path,
        shapes,
        flags,
        other_data,
    ):
        self.filename = filename
        self.image_path = resolved_image_path
        self.resolved_image_path = resolved_image_path
        self.image_data = image_data
        self.shapes = shapes
        self.flags = flags
        self.other_data = other_data


class FileSession:
    """File lifecycle commands of the labeling window."""

    def __init__(self, host):
        self.host = host

    def _ensure_dataset_for_folder(self, directory):
        """Create ``xanylabeling.db`` for a JSON-only folder on first open.

        The source JSON files are imported read-only, so opening a legacy
        project once migrates it into the database and later opens use the DB.
        """

        database_path = Path(directory) / "xanylabeling.db"
        if database_path.is_file():
            return True
        images = [
            path
            for path in utils.scan_all_images(directory)
            if ".trash" not in Path(path).parts
            and "_delete_" not in Path(path).parts
        ]
        if not images:
            return False
        from ...services.dataset.importer import import_xlabel_folder

        QtWidgets.QApplication.setOverrideCursor(
            QtCore.Qt.CursorShape.WaitCursor
        )
        try:
            self.host.status(
                self.host.tr("Creating dataset database…")
            )
            QtWidgets.QApplication.processEvents()
            report = import_xlabel_folder(directory)
        except Exception as exc:  # noqa: BLE001 - fall back to JSON mode
            self.host.error_message(
                self.host.tr("Dataset database"),
                self.host.tr(
                    "Could not create a dataset database in <b>%s</b>:<br/>%s"
                )
                % (directory, exc),
            )
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.host.status(
            self.host.tr("Dataset database created: %s") % database_path
        )
        if report.errors:
            self.host.status(
                self.host.tr(
                    "Dataset database created with %d file errors; see logs."
                )
                % len(report.errors)
            )
        return True

    def _open_dataset_for_folder(self, directory):
        """Open ``<directory>/xanylabeling.db``; False means a hard error."""

        database_path = Path(directory) / "xanylabeling.db"
        if not database_path.is_file():
            return None
        from ...services.dataset import DatasetDatabase, DatasetRepository
        try:
            database = DatasetDatabase.open(database_path)
            repository = DatasetRepository(database)
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            if "database" in locals():
                try:
                    database.close()
                except Exception:  # noqa: BLE001 - preserve original error
                    pass
            self.host.error_message(
                self.host.tr("Error opening dataset"),
                self.host.tr("<b>%s</b><br/>%s") % (database_path, exc),
            )
            return False
        self._close_dataset()
        self.host.dataset_database = database
        self.host.dataset_repository = repository
        self.host.dataset_root = str(Path(directory).resolve())
        self.host.dataset_image_id = None
        self.host.output_dir = None
        # The DB's imported_at is authoritative; a legacy JSON-mode sidecar
        # would only confuse users and is no longer read in DB mode.
        legacy_sidecar = Path(directory) / ".xanylabeling_import_time.json"
        if legacy_sidecar.is_file():
            try:
                legacy_sidecar.unlink()
                logger.info("Removed legacy import-time sidecar: %s", legacy_sidecar)
            except OSError:
                logger.warning(
                    "Could not remove legacy import-time sidecar: %s",
                    legacy_sidecar,
                )
        return repository

    def _close_dataset(self):
        database = getattr(self.host, "dataset_database", None)
        if database is not None:
            try:
                database.close()
            except Exception:  # noqa: BLE001 - best effort on switch/close
                logger.exception("failed to close dataset database")
        self.host.dataset_database = None
        self.host.dataset_repository = None
        self.host.dataset_root = None
        self.host.dataset_image_id = None

    def import_project_dialog(self):
        """Import X-AnyLabeling JSON files into a dataset DB, then open it."""

        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.host,
            self.host.tr("Import Project (X-AnyLabeling)"),
            self.host.current_path(),
        )
        if not directory:
            return
        database_path = Path(directory) / "xanylabeling.db"
        overwrite = "skip"
        if database_path.exists():
            box = QtWidgets.QMessageBox(self.host)
            box.setWindowTitle(self.host.tr("Import Project"))
            box.setText(
                self.host.tr(
                    "A dataset database already exists in this directory."
                )
            )
            box.setInformativeText(
                self.host.tr(
                    "Skip existing images or replace their annotations?"
                )
            )
            skip_button = box.addButton(
                self.host.tr("Skip Existing"),
                QtWidgets.QMessageBox.ButtonRole.AcceptRole,
            )
            replace_button = box.addButton(
                self.host.tr("Replace Existing"),
                QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
            )
            box.addButton(
                self.host.tr("Cancel"), QtWidgets.QMessageBox.ButtonRole.RejectRole
            )
            box.exec()
            if box.clickedButton() is skip_button:
                overwrite = "skip"
            elif box.clickedButton() is replace_button:
                overwrite = "replace"
            else:
                return
        from ...services.dataset.importer import import_xlabel_folder

        try:
            report = import_xlabel_folder(directory, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator
            self.host.error_message(
                self.host.tr("Import failed"), self.host.tr("<b>%s</b>") % exc
            )
            return
        details = [
            self.host.tr("Images: %d") % report.images,
            self.host.tr("Labeled: %d") % report.labeled_images,
            self.host.tr("Objects: %d") % report.objects,
            self.host.tr("Skipped: %d") % report.skipped,
            self.host.tr("Errors: %d") % len(report.errors),
        ]
        if report.backup_path:
            details.append(
                self.host.tr("Backup: %s") % str(report.backup_path)
            )
        if report.errors:
            details.append("")
            details.extend(report.errors[:5])
        QtWidgets.QMessageBox.information(
            self.host,
            self.host.tr("Import Project"),
            "\n".join(details),
        )
        self.host.import_image_folder(directory, load=True)

    def show_trash_dialog(self):
        if getattr(self.host, "dataset_repository", None) is None:
            self.host.status(
                self.host.tr("Recycle bin is available in dataset mode only.")
            )
            return
        from .widgets.trash_dialog import TrashDialog

        dialog = TrashDialog(self.host, parent=self.host)
        dialog.exec()
        if getattr(self.host, "dataset_repository", None) is not None:
            self.host.import_image_folder(self.host.dataset_root, load=True)

    def _trash_current_image(self):
        repository = getattr(self.host, "dataset_repository", None)
        image_id = getattr(self.host, "dataset_image_id", None)
        if repository is None or image_id is None:
            self.host.status(self.host.tr("No dataset image is open."))
            return False
        image = repository.get_image(image_id)
        if image is None:
            return False
        root = Path(self.host.dataset_root)
        source = root / image["rel_path"]
        trash_dir = root / ".trash" / str(image_id)
        target = trash_dir / source.name
        if not source.is_file():
            self.host.error_message(
                self.host.tr("Error deleting image"),
                self.host.tr("<b>%s</b> does not exist.") % source,
            )
            return False
        if target.exists():
            self.host.error_message(
                self.host.tr("Error deleting image"),
                self.host.tr("<b>%s</b> already exists.") % target,
            )
            return False
        trash_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(target))
            repository.delete_image(image_id)
        except Exception as exc:  # noqa: BLE001 - restore the file on failure
            if target.exists() and not source.exists():
                shutil.move(str(target), str(source))
            self.host.error_message(
                self.host.tr("Error deleting image"),
                self.host.tr("<b>%s</b>") % exc,
            )
            return False
        self.host.dataset_image_id = None
        self._load_database_folder(root, repository, load=True)
        if self.host.file_list_widget.count() == 0:
            self.host.reset_state()
        self.host.status(self.host.tr("Image moved to the recycle bin."))
        return True

    @staticmethod
    def _import_timestamp(value):
        if not isinstance(value, str) or not value:
            return 0.0
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return moment.timestamp()

    def _apply_dataset_ui_state(self, dataset_mode):
        """Disable JSON-only review actions while a dataset is open."""

        for name in (
            "toggle_annotation_checked",
            "clear_annotation_checked",
            "fail_annotation_checked",
            "open_next_unchecked_image",
            "open_prev_unchecked_image",
        ):
            action = getattr(self.host.actions, name, None)
            if action is not None:
                action.setEnabled(not dataset_mode)

    @staticmethod
    def _simple_database_filters(pattern):
        """Return SQL-friendly filters or ``None``.

        Only flat forms are optimized: ``label::x`` / ``tags::x`` /
        ``split::train`` / ``shape::0`` and plain filename text, joined by
        commas.  Boolean groups, attributes and regex keep using the full
        in-Python evaluator.
        """

        text = str(pattern or "").strip()
        if not text:
            return [], [], None, False, None
        if any(char in text for char in "()|!"):
            return None
        parts = []
        buffer = []
        escaped = False
        for char in text:
            if escaped:
                buffer.append("\\")
                buffer.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == ",":
                parts.append("".join(buffer).strip())
                buffer = []
            else:
                buffer.append(char)
        parts.append("".join(buffer).strip())
        labels = []
        tags = []
        split = None
        objectless = False
        filename = None
        for part in parts:
            if "::" not in part:
                if not part or filename is not None:
                    return None
                filename = _unescape_filter_value(part)
                continue
            if part.count("::") != 1:
                return None
            field, value = part.split("::", 1)
            field = field.strip().lower()
            value = value.strip()
            if field == "label" and value:
                labels.append(_unescape_filter_value(value))
            elif field == "tags" and value:
                tags.append(_unescape_filter_value(value))
            elif field == "split" and value:
                normalized = value.lower()
                if normalized == "unassigned":
                    normalized = "none"
                if normalized not in SPLIT_KEYS:
                    return None
                split = normalized
            elif field == "shape" and value == "0":
                objectless = True
            else:
                return None
        return labels, tags, split, objectless, filename

    def _load_database_folder(
        self, directory, repository, load=True, pattern=None, select_first=True
    ):
        self.host.last_open_dir = str(directory)
        self.host.filename = None
        self.host._tag_library_all_paths = None
        self.host.update_browse_actions()
        self.host._clear_file_list()

        root = Path(directory)
        rows = repository.image_summaries()
        if pattern:
            query = parse_search_query(pattern)
            if query.is_index:
                index = query.index - 1
                rows = [rows[index]] if 0 <= index < len(rows) else []
            elif not query.matches_all:
                filters = self._simple_database_filters(pattern)
                if filters is not None:
                    labels, tags, split, objectless, filename = filters
                    rows = repository.image_summaries(
                        labels=labels,
                        tags=tags,
                        split=split,
                        objectless=objectless,
                        filename=filename,
                    )
                else:
                    filtered = []
                    for row in rows:
                        file_path = str(root / row["rel_path"])
                        annotation = repository.load_annotation(row["id"])
                        data = {
                            "shapes": annotation.shapes,
                            "flags": annotation.flags,
                            "split": annotation.split,
                            "checked": False,
                            "description": annotation.description,
                            "tags": annotation.tags,
                        }
                        if matches_query_label_data(query, file_path, data):
                            filtered.append(row)
                    rows = filtered
        for row in rows:
            file_path = str(root / row["rel_path"])
            meta = FileMeta(
                True,
                False,
                int(row["object_count"]),
                row["split"],
                self._import_timestamp(row["imported_at"]),
                tuple(row["tags"]),
            )
            self.host.files.append_db_row(file_path, meta)
        self.host.file_list_widget.fill_name_column()
        request_thumbnails = getattr(
            self.host.files, "request_visible_thumbnails", None
        )
        if request_thumbnails is not None:
            request_thumbnails()

        self.host.actions.open_next_image.setEnabled(True)
        self.host.actions.open_prev_image.setEnabled(True)
        self.host.actions.open_next_unchecked_image.setEnabled(True)
        self.host.actions.open_prev_unchecked_image.setEnabled(True)
        self.host.toggle_actions(select_first)
        self._apply_dataset_ui_state(True)
        self.host.status(self.host.tr("Dataset database: %s") % str(root))
        self.host._refresh_statistics_if_visible()
        invalidate_tags = getattr(
            self.host, "_invalidate_tag_library", None
        )
        if invalidate_tags is not None:
            invalidate_tags()
        if self.host.file_list_widget.count() > 0 and select_first:
            self.host._no_selection_slot = True
            try:
                self.host.file_list_widget.setCurrentRow(0)
            finally:
                self.host._no_selection_slot = False
            self.host.filename = self.host._file_path_at(0)
            if load:
                self.host.load_file(self.host.filename)

    def _prepare_database_file(self, filename, repository):
        root = Path(self.host.dataset_root)
        try:
            relative = Path(filename).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            self.host.error_message(
                self.host.tr("Error opening file"),
                self.host.tr("<b>%s</b> is outside the dataset root.") % filename,
            )
            return False
        image = repository.find_image(relative)
        if image is None:
            self.host.error_message(
                self.host.tr("Error opening file"),
                self.host.tr("Image is not registered in the dataset: <b>%s</b>")
                % relative,
            )
            return False
        image_data = LabelFile.load_image_file(filename)
        if not image_data:
            self.host.error_message(
                self.host.tr("Error opening file"),
                self.host.tr("Failed opening image file: <b>%s</b>") % filename,
            )
            return False
        try:
            annotation = repository.load_annotation(image["id"])
            shapes = [Shape().load_from_dict(shape) for shape in annotation.shapes]
        except Exception as exc:  # noqa: BLE001 - invalid stored payload
            self.host.error_message(
                self.host.tr("Error opening file"),
                self.host.tr("<b>%s</b><br/>%s") % (relative, exc),
            )
            return False

        other_data = dict(annotation.extra)
        other_data.update(
            {
                IMAGE_TAGS_FIELD: list(annotation.tags),
                "description": annotation.description,
                "split": annotation.split,
                "relations": annotation.relations,
                CHECKED_FIELD: False,
            }
        )
        if annotation.editor:
            other_data["author"] = annotation.editor
        if annotation.modified_at:
            other_data["modified_at"] = annotation.modified_at

        self.host.dataset_image_id = image["id"]
        self.host.label_file = DatabaseLabelFile(
            filename,
            image_data,
            filename,
            shapes,
            annotation.flags,
            other_data,
        )
        self.host.image_data = image_data
        self.host.image_path = filename
        self.host.other_data = other_data
        with QtCore.QSignalBlocker(self.host.shape_text_edit):
            self.host.shape_text_edit.setPlainText(annotation.description)
        return True

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
            # Clear ``filename`` first so the selection handler (which ignores
            # a click on the already-open file) performs the actual load.
            self.host.filename = None
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

        repository = getattr(self.host, "dataset_repository", None)
        if repository is not None:
            if not self._prepare_database_file(filename, repository):
                return False
            return self._load_image_common(filename)

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
        return self._load_image_common(filename)

    def _load_image_common(self, filename):
        """Load image data already prepared by the JSON/DB branch."""

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
        refresh_tags = getattr(
            self.host, "_refresh_tag_library_if_visible", None
        )
        if refresh_tags is not None:
            refresh_tags()

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

        self._apply_dataset_ui_state(
            getattr(self.host, "dataset_repository", None) is not None
        )
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
        if getattr(self.host, "dataset_repository", None) is not None:
            self.host.status(
                self.host.tr(
                    "Changing the output directory is not available in dataset mode."
                )
            )
            return
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
        if getattr(self.host, "dataset_repository", None) is not None:
            self.host.status(
                self.host.tr(
                    "Save As is not available in dataset mode yet; "
                    "the annotation is stored in the dataset database."
                )
            )
            return
        self.host._save_file(self.host.save_file_dialog())

    def save_file_dialog(self):
        if getattr(self.host, "dataset_repository", None) is not None:
            self.host.status(
                self.host.tr(
                    "Save As is not available in dataset mode yet."
                )
            )
            return ""
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
            return True
        return False

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
        if getattr(self.host, "dataset_repository", None) is not None:
            answer = QtWidgets.QMessageBox.question(
                self.host,
                self.host.tr("Attention"),
                self.host.tr(
                    "Move this image and its annotation to the recycle bin?"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                self._trash_current_image()
            return
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
        if getattr(self.host, "dataset_repository", None) is not None:
            answer = QtWidgets.QMessageBox.question(
                self.host,
                self.host.tr("Attention"),
                self.host.tr(
                    "Move this image and its annotation to the recycle bin?"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                self._trash_current_image()
            return
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
            self.host.import_image_folder(image_path, auto_db=False)

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
        if getattr(self.host, "dataset_repository", None) is not None:
            self.host.status(
                self.host.tr(
                    "Adding files is not available in dataset mode yet; "
                    "use the dataset import/sync entry."
                )
            )
            return
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

    def import_image_folder(
        self, dirpath, pattern=None, load=True, auto_db=True, select_first=True
    ):
        if not self.host.may_continue() or not dirpath:
            return

        if self.host.compare_view_manager.is_active():
            self.host.close_compare_view(confirm=False)

        if auto_db and not pattern:
            self._ensure_dataset_for_folder(dirpath)

        repository = self._open_dataset_for_folder(dirpath)
        if repository is False:
            return
        if repository is not None:
            self._load_database_folder(
                dirpath,
                repository,
                load=load,
                pattern=pattern,
                select_first=select_first,
            )
            return
        self._close_dataset()
        if self.host.output_dir is None:
            self.host.output_dir = getattr(self.host, "_cli_output_dir", None)

        self.host.last_open_dir = dirpath
        self.host.filename = None
        self.host.update_browse_actions()
        self.host._clear_file_list()

        files_on_disk = list(utils.scan_all_images(dirpath))
        if not pattern:
            # Keep the folder-wide tag vocabulary independent of the current
            # search filter.  A search re-import keeps the previous list.
            self.host._tag_library_all_paths = [
                str(path) for path in files_on_disk
            ]
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
        request_thumbnails = getattr(
            self.host.files, "request_visible_thumbnails", None
        )
        if request_thumbnails is not None:
            request_thumbnails()

        self.host.actions.open_next_image.setEnabled(True)
        self.host.actions.open_prev_image.setEnabled(True)
        self.host.actions.open_next_unchecked_image.setEnabled(True)
        self.host.actions.open_prev_unchecked_image.setEnabled(True)
        self.host.toggle_actions(True)
        self._apply_dataset_ui_state(False)
        self.host.open_next_image(load=load)

        if image_files and self.host._config.get("exif_scan_enabled", True):
            self.host.async_exif_scanner.start_scan(image_files)
        self.host._refresh_statistics_if_visible()
        invalidate_tags = getattr(
            self.host, "_invalidate_tag_library", None
        )
        if invalidate_tags is not None:
            invalidate_tags()
