"""Dataset center window (fork.53, T11/P0).

The center is an independent non-modal window: it lists the datasets known to
this installation, shows their overview, lets the operator write a note,
rename, open, relocate, remove the registry record or delete the dataset, and
starts a merge.  It is deliberately not a tab of the labeling sidebar: the
sidebar is per-image context, while this window manages dataset-level objects
(see design doc §4.7).

All user-visible text is translated with ``self.tr`` on this class, so the
extractor records it under ``DatasetCenterWindow`` and Qt looks it up with the
same context at run time.
"""

from __future__ import annotations

import os
import os.path as osp
import shutil
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from ..services.dataset.connection import DatasetDatabase
from ..services.dataset.errors import DatasetError
from ..services.dataset.registry import (
    STATE_ACTIVE,
    STATE_DELETED,
    STATE_MISSING,
    RegistryStore,
)
from ..services.dataset.repository import DatasetRepository
from ..services.identity.session import get_operator_service
from .labeling.utils.style import (
    get_dialog_style,
    get_ok_btn_style,
)
from .labeling.utils.theme import get_theme

logger = __import__("logging").getLogger(__name__)

COLUMN_STATE = 0
COLUMN_NAME = 1
COLUMN_IMAGES = 2
COLUMN_CATEGORIES = 3
COLUMN_TAGS = 4
COLUMN_LAST_OPENED = 5
COLUMN_PATH = 6

STATE_LABELS = {
    STATE_ACTIVE: "可用",
    STATE_MISSING: "缺失",
    STATE_DELETED: "已删除",
}


def _format_time(value: str) -> str:
    if not value:
        return ""
    return value.replace("T", " ")[:19]


class _SecondLoginDialog(QtWidgets.QDialog):
    """Ask for the current operator's password again before a destructive act."""

    def __init__(self, operator_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Confirm your password"))
        self.setModal(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(
            QtWidgets.QLabel(
                self.tr("Operator: %s") % (operator_name or "-")
            )
        )
        self.password_edit = QtWidgets.QLineEdit(self)
        self.password_edit.setEchoMode(
            QtWidgets.QLineEdit.EchoMode.Password
        )
        self.password_edit.setPlaceholderText(self.tr("Password"))
        layout.addWidget(self.password_edit)
        self._error = QtWidgets.QLabel(self)
        self._error.setStyleSheet("color: #d9534f;")
        layout.addWidget(self._error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(320)

    def password(self) -> str:
        return self.password_edit.text()

    def show_error(self, message: str) -> None:
        self._error.setText(message)


class DatasetCenterWindow(QtWidgets.QDialog):
    """Independent dataset manager."""

    open_requested = QtCore.pyqtSignal(str)

    def __init__(
        self,
        registry: RegistryStore | None = None,
        operator_service=None,
        current_dataset_provider=None,
        parent=None,
    ):
        super().__init__(parent)
        self.registry = registry or RegistryStore()
        self.operator_service = operator_service or get_operator_service()
        self.current_dataset_provider = current_dataset_provider
        self._entries = []
        self._overview_cache = {}
        self.setWindowTitle(self.tr("Dataset Center"))
        self.setModal(False)
        self.resize(1040, 620)
        self.setStyleSheet(get_dialog_style())
        self._build_ui()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(6)
        self.add_button = QtWidgets.QPushButton(self.tr("Add Folder…"), self)
        self.add_button.clicked.connect(self._add_folder)
        self.refresh_button = QtWidgets.QPushButton(self.tr("Refresh"), self)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_button = QtWidgets.QPushButton(self.tr("Open"), self)
        self.open_button.clicked.connect(self._open_selected)
        self.rename_button = QtWidgets.QPushButton(self.tr("Rename…"), self)
        self.rename_button.clicked.connect(self._rename_selected)
        self.relocate_button = QtWidgets.QPushButton(
            self.tr("Relocate…"), self
        )
        self.relocate_button.clicked.connect(self._relocate_selected)
        self.merge_button = QtWidgets.QPushButton(self.tr("Merge…"), self)
        self.merge_button.clicked.connect(self._merge_selected)
        self.delete_button = QtWidgets.QPushButton(
            self.tr("Delete Dataset…"), self
        )
        self.delete_button.clicked.connect(self._delete_selected)
        self.remove_button = QtWidgets.QPushButton(
            self.tr("Remove Record"), self
        )
        self.remove_button.clicked.connect(self._remove_selected)
        for button in (
            self.add_button,
            self.refresh_button,
            self.open_button,
            self.rename_button,
            self.relocate_button,
            self.merge_button,
            self.delete_button,
            self.remove_button,
        ):
            button.setStyleSheet(get_ok_btn_style())
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.search_edit = QtWidgets.QLineEdit(self)
        self.search_edit.setPlaceholderText(self.tr("Search datasets…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_edit, 1)
        layout.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("State"),
                self.tr("Name"),
                self.tr("Images"),
                self.tr("Classes"),
                self.tr("Tags"),
                self.tr("Last opened"),
                self.tr("Path"),
            ]
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._open_selected)
        splitter.addWidget(self.table)

        detail = QtWidgets.QWidget(self)
        detail_layout = QtWidgets.QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)
        overview_box = QtWidgets.QGroupBox(self.tr("Overview"), detail)
        overview_layout = QtWidgets.QVBoxLayout(overview_box)
        self.overview_label = QtWidgets.QLabel(
            self.tr("Select a dataset to see its overview."), overview_box
        )
        self.overview_label.setWordWrap(True)
        self.overview_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        overview_layout.addWidget(self.overview_label)
        detail_layout.addWidget(overview_box, 1)

        note_box = QtWidgets.QGroupBox(self.tr("Dataset note"), detail)
        note_layout = QtWidgets.QVBoxLayout(note_box)
        self.note_edit = QtWidgets.QPlainTextEdit(note_box)
        self.note_edit.setPlaceholderText(
            self.tr("Notes about this dataset (requires login)")
        )
        note_layout.addWidget(self.note_edit)
        note_buttons = QtWidgets.QHBoxLayout()
        note_buttons.addStretch(1)
        self.save_note_button = QtWidgets.QPushButton(
            self.tr("Save Note"), note_box
        )
        self.save_note_button.setStyleSheet(get_ok_btn_style())
        self.save_note_button.clicked.connect(self._save_note)
        note_buttons.addWidget(self.save_note_button)
        note_layout.addLayout(note_buttons)
        detail_layout.addWidget(note_box)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        close_buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close, self
        )
        close_buttons.rejected.connect(self.reject)
        layout.addWidget(close_buttons)

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._entries = self.registry.list()
        for entry in list(self._entries):
            if entry.state != STATE_ACTIVE:
                continue
            check = self.registry.check_dataset(entry.db_path)
            if check.ok:
                continue
            logger.warning(
                "Dataset registry entry %s is missing: %s",
                entry.uuid,
                check.reason,
            )
            self.registry.mark_missing(
                entry.uuid,
                reason=check.reason,
                operator_id=self._operator_id(),
            )
        self._entries = self.registry.list()
        self._overview_cache = {}
        self._fill_table()

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        theme = get_theme()
        for entry in self._entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            counts = {"images": "", "categories": "", "tags": ""}
            if entry.state == STATE_ACTIVE:
                overview = self._load_overview(entry)
                if overview is not None:
                    totals = overview["totals"]
                    counts = {
                        "images": str(totals["images"]),
                        "categories": str(totals["categories"]),
                        "tags": str(totals["tag_kinds"]),
                    }
            values = [
                STATE_LABELS.get(entry.state, entry.state),
                entry.display_name or entry.uuid[:8],
                counts["images"],
                counts["categories"],
                counts["tags"],
                _format_time(entry.last_opened_at),
                entry.db_path,
            ]
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if column == COLUMN_STATE and entry.state != STATE_ACTIVE:
                    item.setForeground(QtCore.Qt.GlobalColor.red)
                self.table.setItem(row, column, item)
            self.table.item(row, COLUMN_NAME).setData(
                QtCore.Qt.ItemDataRole.UserRole, entry.uuid
            )
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        self._apply_filter(self.search_edit.text())
        if self._entries:
            self.table.selectRow(0)
            self._on_selection_changed()
        else:
            self.overview_label.setText(
                self.tr("No datasets yet. Use Add Folder… to register one.")
            )
            self.note_edit.clear()

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().casefold()
        for row in range(self.table.rowCount()):
            values = []
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is not None:
                    values.append(item.text().casefold())
            hidden = bool(needle) and not any(
                needle in value for value in values
            )
            self.table.setRowHidden(row, hidden)

    def _selected_entries(self) -> list:
        uuid_by_row = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COLUMN_NAME)
            if item is not None:
                uuid_by_row[row] = item.data(QtCore.Qt.ItemDataRole.UserRole)
        selections = {
            index.row() for index in self.table.selectionModel().selectedRows()
        }
        result = []
        for row in sorted(selections):
            uuid = uuid_by_row.get(row)
            if not uuid:
                continue
            for entry in self._entries:
                if entry.uuid == uuid:
                    result.append(entry)
                    break
        return result

    def _entry_for_row(self, row: int):
        item = self.table.item(row, COLUMN_NAME)
        if item is None:
            return None
        uuid = item.data(QtCore.Qt.ItemDataRole.UserRole)
        for entry in self._entries:
            if entry.uuid == uuid:
                return entry
        return None

    def _load_overview(self, entry):
        cached = self._overview_cache.get(entry.uuid)
        if cached is not None:
            return cached
        try:
            database = DatasetDatabase.open(entry.db_path, read_only=True)
        except Exception:  # noqa: BLE001 - missing entries are reported in UI
            return None
        try:
            repository = DatasetRepository(database)
            overview = repository.overview()
        except DatasetError:
            return None
        finally:
            database.close()
        self._overview_cache[entry.uuid] = overview
        return overview

    # -- selection ---------------------------------------------------------
    def _on_selection_changed(self) -> None:
        entries = self._selected_entries()
        if len(entries) != 1:
            self.overview_label.setText(
                self.tr("%d datasets selected.") % len(entries)
                if entries
                else self.tr("Select a dataset to see its overview.")
            )
            self.note_edit.clear()
            return
        entry = entries[0]
        overview = self._load_overview(entry) if entry.state == STATE_ACTIVE else None
        if overview is None:
            self.overview_label.setText(
                self.tr("This dataset is %s: %s")
                % (
                    STATE_LABELS.get(entry.state, entry.state),
                    entry.db_path,
                )
            )
            self.note_edit.clear()
            return
        totals = overview["totals"]
        splits = overview["splits"]
        lines = [
            self.tr("Name: %s") % (entry.display_name or overview["dataset"]["name"] or "-"),
            self.tr("Path: %s") % entry.db_path,
            self.tr("Images: %d (recycle bin: %d)") % (
                totals["images"], totals["trashed"]
            ),
            self.tr("Objects: %d · Classes: %d · Tag kinds: %d") % (
                totals["objects"], totals["categories"], totals["tag_kinds"]
            ),
            self.tr("Split: train %d · val %d · test %d · none %d") % (
                splits["train"], splits["val"], splits["test"], splits["none"]
            ),
        ]
        top_tags = overview["tags"][:15]
        if top_tags:
            lines.append(
                self.tr("Tags: ")
                + ", ".join(
                    "%s (%d)" % (row["tag"], row["image_count"])
                    for row in top_tags
                )
            )
        top_categories = overview["categories"][:10]
        if top_categories:
            lines.append(
                self.tr("Classes: ")
                + ", ".join(
                    "%s (%d/%d)"
                    % (row["name"], row["image_count"], row["object_count"])
                    for row in top_categories
                )
            )
        self.overview_label.setText("\n".join(lines))
        self.note_edit.setPlainText(overview["dataset"].get("description", ""))

    # -- login helpers -----------------------------------------------------
    def _operator(self):
        return getattr(self.operator_service.session, "operator", None)

    def _operator_id(self):
        operator = self._operator()
        return getattr(operator, "id", None) if operator else None

    def _require_login(self):
        operator = self._operator()
        if operator is None:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Login required"),
                self.tr("Please log in before changing a dataset."),
            )
            return None
        return operator

    def _confirm_password(self, operator) -> bool:
        dialog = _SecondLoginDialog(operator.name, self)
        while dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                self.operator_service.store.authenticate(
                    operator.name, dialog.password()
                )
            except Exception as error:  # noqa: BLE001 - shown in the dialog
                dialog.show_error(str(error))
                continue
            return True
        return False

    # -- actions -----------------------------------------------------------
    def _add_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("Add Dataset Folder"), ""
        )
        if not folder:
            return
        try:
            self.registry.add_from_folder(
                folder, operator_id=self._operator_id()
            )
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Cannot add dataset"),
                self.tr(
                    "The folder must contain an existing xanylabeling.db "
                    "dataset database.\n\n%s"
                )
                % error,
            )
            return
        self.refresh()

    def _open_selected(self) -> None:
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        if entry.state != STATE_ACTIVE:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Dataset unavailable"),
                self.tr("This dataset is missing or deleted."),
            )
            return
        check = self.registry.check_dataset(entry.db_path)
        if not check.ok:
            self.refresh()
            return
        self.registry.touch(entry.uuid, operator_id=self._operator_id())
        self._overview_cache.pop(entry.uuid, None)
        self.open_requested.emit(check.root)
        self.accept()

    def _rename_selected(self) -> None:
        operator = self._require_login()
        if operator is None:
            return
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        value, accepted = QtWidgets.QInputDialog.getText(
            self,
            self.tr("Rename Dataset"),
            self.tr("New name:"),
            text=entry.display_name,
        )
        if not accepted:
            return
        try:
            self.registry.rename(entry.uuid, value, operator_id=operator.id)
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self, self.tr("Rename failed"), str(error)
            )
            return
        self.refresh()

    def _relocate_selected(self) -> None:
        operator = self._require_login()
        if operator is None:
            return
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("Select the folder that contains xanylabeling.db")
        )
        if not folder:
            return
        try:
            self.registry.relocate(
                entries[0].uuid,
                osp.join(folder, "xanylabeling.db"),
                operator_id=operator.id,
            )
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self, self.tr("Relocate failed"), str(error)
            )
            return
        self.refresh()

    def _save_note(self) -> None:
        operator = self._require_login()
        if operator is None:
            return
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        if entry.state != STATE_ACTIVE:
            return
        try:
            database = DatasetDatabase.open(entry.db_path)
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self, self.tr("Cannot save the note"), str(error)
            )
            return
        try:
            repository = DatasetRepository(database)
            repository.update_dataset_metadata(
                description=self.note_edit.toPlainText()
            )
        except DatasetError as error:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Cannot save the note"), str(error)
            )
            return
        finally:
            database.close()
        self._overview_cache.pop(entry.uuid, None)
        self.refresh()

    def _current_dataset_root(self):
        if self.current_dataset_provider is None:
            return None
        try:
            return self.current_dataset_provider()
        except Exception:  # noqa: BLE001 - provider is best effort
            return None

    def _delete_selected(self) -> None:
        operator = self._require_login()
        if operator is None:
            return
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        entry = entries[0]
        if entry.state == STATE_DELETED:
            return
        current_root = self._current_dataset_root()
        if current_root and os.path.normcase(
            osp.abspath(entry.root_path or "")
        ) == os.path.normcase(osp.abspath(current_root)):
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Dataset is open"),
                self.tr(
                    "This dataset is open in the labeling window. Switch to "
                    "another dataset before deleting it."
                ),
            )
            return
        if not self._confirm_password(operator):
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self.tr("Delete dataset"))
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setText(
            self.tr("Delete “%s”?") % (entry.display_name or entry.uuid[:8])
        )
        box.setInformativeText(
            self.tr(
                "The database is backed up first. “Database and images” "
                "also deletes the image files and cannot be undone."
            )
        )
        db_only = box.addButton(
            self.tr("Database only"), QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        with_images = box.addButton(
            self.tr("Database and images"),
            QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
        )
        box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is db_only:
            mode = "database"
        elif clicked is with_images:
            mode = "database_and_images"
        else:
            return
        backup_path = ""
        try:
            backup_path = str(self._backup_dataset(entry))
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Backup failed"),
                self.tr("The dataset was not deleted.\n\n%s") % error,
            )
            return
        try:
            self._delete_files(entry, mode)
        except Exception as error:  # noqa: BLE001 - shown to the operator
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Delete failed"),
                self.tr("Backup: %s\n\n%s") % (backup_path, error),
            )
            return
        self.registry.mark_deleted(
            entry.uuid,
            operator_id=operator.id,
            delete_mode=mode,
            backup_path=backup_path,
        )
        logger.info(
            "Deleted dataset %s (%s) by %s; backup=%s",
            entry.uuid,
            mode,
            operator.name,
            backup_path,
        )
        self.refresh()

    def _backup_dataset(self, entry) -> Path:
        backup_dir = Path(entry.root_path or osp.dirname(entry.db_path)) / ".backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = QtCore.QDateTime.currentDateTime().toString(
            "yyyyMMdd-HHmmss"
        )
        target = backup_dir / f"xanylabeling-{stamp}.db"
        database = DatasetDatabase.open(entry.db_path)
        try:
            return database.backup_to(target)
        finally:
            database.close()

    def _delete_files(self, entry, mode: str) -> None:
        db_path = Path(entry.db_path)
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(db_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        if mode == "database_and_images":
            root = Path(entry.root_path or db_path.parent)
            if root.exists():
                shutil.rmtree(root)

    def _remove_selected(self) -> None:
        operator = self._require_login()
        if operator is None:
            return
        entries = self._selected_entries()
        if not entries:
            return
        box = QtWidgets.QMessageBox.question(
            self,
            self.tr("Remove record"),
            self.tr(
                "Remove %d record(s) from the registry? The dataset files are "
                "not touched."
            )
            % len(entries),
        )
        if box != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        for entry in entries:
            try:
                self.registry.remove_record(
                    entry.uuid, operator_id=operator.id
                )
            except Exception:  # noqa: BLE001 - best effort per entry
                logger.exception("failed to remove registry entry %s", entry.uuid)
        self.refresh()

    def _merge_selected(self) -> None:
        operator = self._require_login()
        if operator is None:
            return
        entries = [
            entry
            for entry in self._selected_entries()
            if entry.state == STATE_ACTIVE
        ]
        if not entries:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("Merge datasets"),
                self.tr("Select at least one available dataset to merge."),
            )
            return
        from .dataset_center_merge import MergeDialog

        dialog = MergeDialog(
            sources=entries,
            registry=self.registry,
            operator_service=self.operator_service,
            current_dataset_root=self._current_dataset_root(),
            parent=self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        created_root = dialog.created_dataset_root
        self.refresh()
        if created_root:
            self.open_requested.emit(created_root)
            self.accept()
