"""Duplicate review dialog shared by merge and folder import (fork.62).

The dialog never decides on its own: every exact-duplicate group gets an
explicit action chosen by the operator (``keep_both``/``keep_one`` for
identical annotations, ``keep_both``/``merge_annotations`` otherwise).
"""

from PyQt6 import QtCore, QtWidgets

from ..services.dataset.duplicates import (
    ACTION_KEEP_BOTH,
)


class DuplicateReviewDialog(QtWidgets.QDialog):
    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self._groups = list(groups)
        self._choices = {}
        self._combos = {}
        self.setWindowTitle(self.tr("Exact duplicate images"))
        self.setModal(True)
        self.resize(860, 460)
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            self.tr(
                "These images have identical file bytes (SHA-256). "
                "Choose what to do with each group; the first image is "
                "always kept."
            ),
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QtWidgets.QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Group"),
                self.tr("Verdict"),
                self.tr("Sources"),
                self.tr("Files"),
                self.tr("Annotations"),
                self.tr("Action"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.keep_all_button = QtWidgets.QPushButton(
            self.tr("Keep all"), self
        )
        self.keep_all_button.clicked.connect(self._keep_all)
        buttons.addWidget(self.keep_all_button)
        buttons.addStretch()
        self.ok_button = QtWidgets.QPushButton(self.tr("Apply"), self)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._apply)
        cancel_button = QtWidgets.QPushButton(self.tr("Cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)
        self._rebuild()

    def _rebuild(self):
        self.table.setRowCount(len(self._groups))
        for row, group in enumerate(self._groups):
            entry = group.entries[0]
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(
                group.sha256[:12]
            ))
            verdict = (
                self.tr("Same annotation")
                if group.same_annotation
                else self.tr("Different annotations")
            )
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(verdict))
            sources = ", ".join(
                sorted({item.source for item in group.entries})
            )
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(sources))
            details = "\n".join(
                "%s  (%d objects)" % (item.path, item.object_count)
                for item in group.entries
            )
            files_item = QtWidgets.QTableWidgetItem(
                str(len(group.entries))
            )
            files_item.setToolTip(details)
            self.table.setItem(row, 3, files_item)
            annotations = self.tr("%d objects") % entry.object_count
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(annotations))
            combo = QtWidgets.QComboBox(self.table)
            labels = {
                ACTION_KEEP_BOTH: self.tr("Keep both"),
                "keep_one": self.tr("Keep one"),
                "merge_annotations": self.tr("Merge annotations"),
            }
            for action in group.action_options():
                combo.addItem(labels[action], action)
            default = (
                ACTION_KEEP_BOTH
                if ACTION_KEEP_BOTH in group.action_options()
                else group.action_options()[0]
            )
            combo.setCurrentIndex(combo.findData(default))
            combo.currentIndexChanged.connect(
                lambda _index, sha=group.sha256, box=combo: (
                    self._choices.__setitem__(sha, box.currentData())
                )
            )
            self._choices[group.sha256] = default
            self._combos[group.sha256] = combo
            self.table.setCellWidget(row, 5, combo)

    def _keep_all(self):
        for group in self._groups:
            combo = self._combos[group.sha256]
            index = combo.findData(ACTION_KEEP_BOTH)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _apply(self):
        self.accept()

    def choices(self) -> dict:
        """``{sha256: action}`` for every group."""

        return dict(self._choices)
