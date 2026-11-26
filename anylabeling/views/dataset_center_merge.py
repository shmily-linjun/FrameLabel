"""Merge wizard for the dataset center (fork.53, T11/P1).

The dialog collects the merge decisions (target, category mapping, split
policy), shows the dry-run report and then runs
:func:`anylabeling.services.dataset.merge.merge_datasets` in a worker thread so
the window stays responsive.

All text is translated with ``self.tr`` inside this class, so the extractor and
Qt agree on the ``MergeDialog`` context.
"""

from __future__ import annotations

import os.path as osp
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from ..services.dataset.merge import (
    MergeOptions,
    create_target_dataset,
    merge_datasets,
    plan_merge,
)
from ..services.dataset.registry import RegistryStore
from .labeling.utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
    get_settings_combo_style,
)
from anylabeling.views.file_dialogs import choose_directory


class _MergeWorker(QtCore.QThread):
    progress_changed = QtCore.pyqtSignal(int, int)
    finished_report = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, sources, target_db, options, parent=None):
        super().__init__(parent)
        self._sources = list(sources)
        self._target_db = target_db
        self._options = options

    def run(self):  # noqa: D401 - QThread entry point
        try:
            report = merge_datasets(
                self._sources,
                self._target_db,
                self._options,
                progress=lambda done, total: self.progress_changed.emit(
                    done, total
                ),
            )
        except Exception as error:  # noqa: BLE001 - reported in the dialog
            self.failed.emit(str(error))
            return
        self.finished_report.emit(report)


class MergeDialog(QtWidgets.QDialog):
    """Collect merge decisions and execute the merge."""

    def __init__(
        self,
        sources,
        registry: RegistryStore,
        operator_service,
        current_dataset_root: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.sources = list(sources)
        self.registry = registry
        self.operator_service = operator_service
        self.current_dataset_root = current_dataset_root
        self.created_dataset_root = ""
        self._worker = None
        self._report = None
        self._plan = None
        self.setWindowTitle(self.tr("Merge Datasets"))
        self.setModal(True)
        self.resize(860, 640)
        self.setStyleSheet(get_dialog_style())
        self._build_ui()
        self._load_targets()
        self._load_categories()

    # -- construction ------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        source_names = ", ".join(
            entry.display_name or entry.uuid[:8] for entry in self.sources
        )
        layout.addWidget(
            QtWidgets.QLabel(
                self.tr("Sources (%d): %s") % (len(self.sources), source_names)
            )
        )

        target_box = QtWidgets.QGroupBox(self.tr("Target dataset"), self)
        target_layout = QtWidgets.QVBoxLayout(target_box)
        self.existing_radio = QtWidgets.QRadioButton(
            self.tr("Merge into an existing dataset"), target_box
        )
        self.existing_combo = QtWidgets.QComboBox(target_box)
        self.existing_combo.setStyleSheet(get_settings_combo_style())
        self.new_radio = QtWidgets.QRadioButton(
            self.tr("Create a new dataset and merge into it"), target_box
        )
        new_row = QtWidgets.QHBoxLayout()
        self.name_edit = QtWidgets.QLineEdit(target_box)
        self.name_edit.setPlaceholderText(self.tr("New dataset name"))
        self.folder_edit = QtWidgets.QLineEdit(target_box)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText(
            self.tr("Parent folder for the new dataset")
        )
        self.folder_button = QtWidgets.QPushButton(
            self.tr("Choose Folder…"), target_box
        )
        self.folder_button.clicked.connect(self._choose_folder)
        new_row.addWidget(self.name_edit, 1)
        new_row.addWidget(self.folder_edit, 1)
        new_row.addWidget(self.folder_button)
        target_layout.addWidget(self.existing_radio)
        target_layout.addWidget(self.existing_combo)
        target_layout.addWidget(self.new_radio)
        target_layout.addLayout(new_row)
        layout.addWidget(target_box)

        options_box = QtWidgets.QGroupBox(self.tr("Options"), self)
        options_layout = QtWidgets.QVBoxLayout(options_box)
        self.keep_split_check = QtWidgets.QCheckBox(
            self.tr("Keep the source split (train/val/test/none)"), options_box
        )
        self.keep_split_check.setChecked(True)
        self.skip_empty_check = QtWidgets.QCheckBox(
            self.tr("Skip source classes without objects"), options_box
        )
        self.check_duplicates_check = QtWidgets.QCheckBox(
            self.tr("Report suspected duplicates (same name, size and time)"),
            options_box,
        )
        self.check_duplicates_check.setChecked(True)
        options_layout.addWidget(self.keep_split_check)
        options_layout.addWidget(self.skip_empty_check)
        options_layout.addWidget(self.check_duplicates_check)
        layout.addWidget(options_box)

        mapping_box = QtWidgets.QGroupBox(
            self.tr("Class mapping (optional)"), self
        )
        mapping_layout = QtWidgets.QVBoxLayout(mapping_box)
        self.mapping_table = QtWidgets.QTableWidget(mapping_box)
        self.mapping_table.setColumnCount(3)
        self.mapping_table.setHorizontalHeaderLabels(
            [
                self.tr("Source dataset"),
                self.tr("Source class"),
                self.tr("Target class"),
            ]
        )
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        mapping_layout.addWidget(self.mapping_table)
        layout.addWidget(mapping_box, 1)

        self.report_label = QtWidgets.QLabel(self)
        self.report_label.setWordWrap(True)
        self.report_label.setText(self.tr("Choose a target and run Preview."))
        layout.addWidget(self.report_label)

        buttons = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton(self.tr("Preview"), self)
        self.preview_button.setStyleSheet(get_cancel_btn_style())
        self.preview_button.clicked.connect(self._preview)
        self.merge_button = QtWidgets.QPushButton(self.tr("Start Merge"), self)
        self.merge_button.setStyleSheet(get_ok_btn_style())
        self.merge_button.clicked.connect(self._start_merge)
        self.merge_button.setEnabled(False)
        cancel_button = QtWidgets.QPushButton(self.tr("Cancel"), self)
        cancel_button.setStyleSheet(get_cancel_btn_style())
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.preview_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.merge_button)
        layout.addLayout(buttons)

        self.existing_radio.toggled.connect(self._on_target_changed)
        self.new_radio.toggled.connect(self._on_target_changed)
        self.existing_combo.currentIndexChanged.connect(self._on_target_changed)
        self.name_edit.textChanged.connect(self._on_target_changed)

    # -- helpers -----------------------------------------------------------
    def _load_targets(self) -> None:
        entries = [
            entry
            for entry in self.registry.list()
            if entry.state == "active"
        ]
        self._target_entries = entries
        self.existing_combo.clear()
        for entry in entries:
            label = entry.display_name or entry.uuid[:8]
            self.existing_combo.addItem(f"{label} ({entry.db_path})", entry)
        current = None
        if self.current_dataset_root:
            for entry in entries:
                if osp.normcase(entry.root_path) == osp.normcase(
                    self.current_dataset_root
                ):
                    current = entry
                    break
        if current is not None:
            index = self.existing_combo.findData(current)
            if index >= 0:
                self.existing_combo.setCurrentIndex(index)
        self.existing_radio.setChecked(bool(entries))
        self.new_radio.setChecked(not entries)
        self._on_target_changed()

    def _load_categories(self) -> None:
        from ..services.dataset.merge import _read_source

        rows = []
        for entry in self.sources:
            try:
                source = _read_source(entry.db_path)
            except Exception:  # noqa: BLE001 - missing source is reported later
                continue
            for category in source.categories.values():
                if category["is_deleted"]:
                    continue
                rows.append(
                    (entry.display_name or entry.uuid[:8], category["name"])
                )
        self.mapping_table.setRowCount(len(rows))
        for row, (source_name, category_name) in enumerate(rows):
            self.mapping_table.setItem(
                row, 0, QtWidgets.QTableWidgetItem(source_name)
            )
            source_item = QtWidgets.QTableWidgetItem(category_name)
            source_item.setFlags(
                source_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self.mapping_table.setItem(row, 1, source_item)
            self.mapping_table.setItem(
                row, 2, QtWidgets.QTableWidgetItem(category_name)
            )

    def _choose_folder(self) -> None:
        folder = choose_directory(
            self, self.tr("Parent folder for the new dataset")
        )
        if folder:
            self.folder_edit.setText(folder)

    def _on_target_changed(self, *args) -> None:
        existing = self.existing_radio.isChecked()
        self.existing_combo.setEnabled(existing)
        self.new_radio.setEnabled(True)
        self.name_edit.setEnabled(not existing)
        self.folder_edit.setEnabled(not existing)
        self.folder_button.setEnabled(not existing)
        self.merge_button.setEnabled(False)
        self.report_label.setText(self.tr("Run Preview to check the merge."))

    def _category_map(self) -> dict:
        mapping = {}
        for row in range(self.mapping_table.rowCount()):
            source_item = self.mapping_table.item(row, 1)
            target_item = self.mapping_table.item(row, 2)
            if source_item is None or target_item is None:
                continue
            source_name = source_item.text().strip()
            target_name = target_item.text().strip()
            if source_name and target_name and source_name != target_name:
                mapping[source_name] = target_name
        return mapping

    def _options(self) -> MergeOptions:
        uniform = None if self.keep_split_check.isChecked() else None
        return MergeOptions(
            keep_split=self.keep_split_check.isChecked(),
            uniform_split=uniform,
            category_map=self._category_map(),
            skip_empty_categories=self.skip_empty_check.isChecked(),
            check_duplicates=self.check_duplicates_check.isChecked(),
        )

    def _target_db(self) -> str:
        if self.existing_radio.isChecked():
            entry = self.existing_combo.currentData()
            if entry is None:
                return ""
            return entry.db_path
        return ""

    def _ensure_new_target(self) -> str:
        name = self.name_edit.text().strip()
        folder = self.folder_edit.text().strip()
        if not name or not folder:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Target required"),
                self.tr("Choose a name and a parent folder for the new dataset."),
            )
            return ""
        try:
            db_path = create_target_dataset(folder, name)
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self, self.tr("Cannot create the target"), str(error)
            )
            return ""
        self.created_dataset_root = str(Path(db_path).parent)
        try:
            self.registry.add_from_folder(
                self.created_dataset_root,
                display_name=name,
                operator_id=getattr(
                    self.operator_service.session.operator, "id", None
                ),
            )
        except Exception:  # noqa: BLE001 - registry is best effort
            pass
        return db_path

    # -- actions -----------------------------------------------------------
    def _preview(self) -> None:
        target_db = self._target_db()
        if not target_db:
            self.report_label.setText(
                self.tr("Creating a new dataset starts the merge directly.")
            )
            self.merge_button.setEnabled(True)
            return
        try:
            self._plan = plan_merge(
                [entry.db_path for entry in self.sources],
                target_db,
                self._options(),
            )
        except Exception as error:  # noqa: BLE001 - shown in the report label
            self.report_label.setText(
                self.tr("Preview failed: %s") % error
            )
            return
        summary = self._plan.summary()
        self.report_label.setText(
            self.tr(
                "Images: %(images)d · Objects: %(objects)d · Suspected "
                "duplicates: %(duplicates)d · Missing files: %(missing)d · "
                "Class decisions: %(categories)d"
            )
            % {
                "images": summary["new_images"],
                "objects": summary["new_objects"],
                "duplicates": summary["duplicate_images"],
                "missing": summary["missing_images"],
                "categories": summary["categories"],
            }
        )
        self.merge_button.setEnabled(True)

    def _start_merge(self) -> None:
        target_db = self._target_db()
        if not target_db:
            target_db = self._ensure_new_target()
            if not target_db:
                return
        options = self._options()
        self.merge_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.progress = QtWidgets.QProgressDialog(
            self.tr("Merging datasets…"), None, 0, 100, self
        )
        self.progress.setWindowTitle(self.tr("Merge Datasets"))
        self.progress.setWindowModality(
            QtCore.Qt.WindowModality.WindowModal
        )
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.show()
        self._worker = _MergeWorker(
            [entry.db_path for entry in self.sources],
            target_db,
            options,
            self,
        )
        self._worker.progress_changed.connect(self._on_progress)
        self._worker.finished_report.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_finished(self, report) -> None:
        self._report = report
        self.progress.close()
        self.preview_button.setEnabled(True)
        message = self.tr(
            "Merged %(images)d images and %(objects)d objects; skipped "
            "%(skipped)d."
        ) % {
            "images": report.imported_images,
            "objects": report.imported_objects,
            "skipped": report.skipped_images,
        }
        if report.errors:
            message += "\n\n" + self.tr("Problems:") + "\n" + "\n".join(
                report.errors[:20]
            )
        if report.backup_path:
            message += "\n\n" + self.tr("Backup: %s") % report.backup_path
        QtWidgets.QMessageBox.information(
            self, self.tr("Merge finished"), message
        )
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.progress.close()
        self.preview_button.setEnabled(True)
        self.merge_button.setEnabled(True)
        QtWidgets.QMessageBox.warning(
            self, self.tr("Merge failed"), message
        )
