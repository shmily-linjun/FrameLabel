"""Recycle bin dialog for dataset mode.

Images deleted in DB mode are soft-deleted in ``image_file`` and moved to
``<dataset>/.trash/<image_id>/``.  This dialog lists those rows and offers
restore / permanent delete / empty.  It deliberately only touches DB mode;
JSON mode keeps the legacy ``_delete_`` folder behavior.
"""

import os
import shutil
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

TRANSLATION_CONTEXT = "TrashDialog"


class TrashDialog(QtWidgets.QDialog):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.repository = host.dataset_repository
        self.root = Path(host.dataset_root)
        self.changed = False
        self.setWindowTitle(self._tr("Recycle Bin"))
        self.resize(640, 360)
        self._build_ui()
        self.refresh()

    def _tr(self, text):
        return QtCore.QCoreApplication.translate(TRANSLATION_CONTEXT, text)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(
            [self._tr("Image"), self._tr("Deleted at")]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        layout.addWidget(self.table, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.restore_button = QtWidgets.QPushButton(self._tr("Restore"))
        self.purge_button = QtWidgets.QPushButton(
            self._tr("Delete Permanently")
        )
        self.empty_button = QtWidgets.QPushButton(self._tr("Empty Recycle Bin"))
        close_button = QtWidgets.QPushButton(self._tr("Close"))
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.purge_button)
        buttons.addWidget(self.empty_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.restore_button.clicked.connect(self._restore)
        self.purge_button.clicked.connect(self._purge)
        self.empty_button.clicked.connect(self._empty)
        close_button.clicked.connect(self.accept)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.refresh()

    def _rows(self):
        return self.repository.list_trash()

    def refresh(self):
        rows = self._rows()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                name = QtWidgets.QTableWidgetItem(row["rel_path"])
                name.setData(QtCore.Qt.ItemDataRole.UserRole, row["id"])
                self.table.setItem(index, 0, name)
                deleted = QtWidgets.QTableWidgetItem(
                    row.get("deleted_at") or ""
                )
                self.table.setItem(index, 1, deleted)
        finally:
            self.table.blockSignals(False)
        self._update_buttons()

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self):
        enabled = self._selected() is not None
        self.restore_button.setEnabled(enabled)
        self.purge_button.setEnabled(enabled)
        self.empty_button.setEnabled(self.table.rowCount() > 0)

    def _image(self, image_id):
        return self.repository.get_image(image_id, include_deleted=True)

    def _trash_file(self, image_id, image):
        return self.root / ".trash" / str(image_id) / Path(image["rel_path"]).name

    def _restore(self):
        image_id = self._selected()
        if image_id is None:
            return
        image = self._image(image_id)
        if image is None:
            self.refresh()
            return
        source = self._trash_file(image_id, image)
        target = self.root / image["rel_path"]
        if not source.is_file():
            QtWidgets.QMessageBox.warning(
                self,
                self._tr("Restore failed"),
                self._tr("The trashed file is missing: %s") % source,
            )
            return
        if target.exists():
            QtWidgets.QMessageBox.warning(
                self,
                self._tr("Restore failed"),
                self._tr("The original path already exists: %s") % target,
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(target))
            self.repository.restore_image(image_id)
        except Exception as exc:  # noqa: BLE001 - restore the file on failure
            if target.exists() and not source.exists():
                shutil.move(str(target), str(source))
            QtWidgets.QMessageBox.warning(
                self,
                self._tr("Restore failed"),
                str(exc),
            )
            return
        self.changed = True
        self.refresh()

    def _purge(self):
        image_id = self._selected()
        if image_id is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self._tr("Delete Permanently"),
            self._tr("Permanently delete this image? This cannot be undone."),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if not self.repository.purge_image(image_id):
            QtWidgets.QMessageBox.warning(
                self,
                self._tr("Delete Permanently"),
                self._tr("The database row could not be deleted."),
            )
            return
        shutil.rmtree(self.root / ".trash" / str(image_id), ignore_errors=True)
        self.changed = True
        self.refresh()

    def _empty(self):
        if self.table.rowCount() == 0:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self._tr("Empty Recycle Bin"),
            self._tr("Permanently delete every trashed image?"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        failed = False
        for row in self._rows():
            if not self.repository.purge_image(row["id"]):
                failed = True
                continue
            shutil.rmtree(
                self.root / ".trash" / str(row["id"]), ignore_errors=True
            )
        self.changed = True
        self.refresh()
        if failed:
            QtWidgets.QMessageBox.warning(
                self,
                self._tr("Empty Recycle Bin"),
                self._tr("Some database rows could not be deleted."),
            )
