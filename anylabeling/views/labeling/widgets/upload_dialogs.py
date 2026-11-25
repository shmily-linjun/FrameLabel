"""Option dialogs used by the upload flow (fork.49).

They all inherit :class:`~.base_dialog.BaseDialog` (or a Qt dialog class with
the same translation discipline) so that a new upload dialog copies one
template instead of re-implementing the path row, the buttons and the
confirmation box.  See :mod:`.base_dialog` for the translation rules.
"""

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from ..utils.style import (
    get_msg_box_style,
    get_progress_dialog_style,
)
from .base_dialog import BaseDialog


class UploadFolderDialog(BaseDialog):
    """Ask where the annotation files live.

    ``extra_builder`` receives the dialog and may add rows between the path
    row and the buttons (class-source hints, category switches, ...).  It is
    a callback rather than a subclass on purpose: inherited ``self.tr`` calls
    would be registered under the base context but looked up with the
    subclass name.
    """

    def __init__(
        self,
        parent=None,
        *,
        initial_path="",
        placeholder="",
        hint_text="",
        preserve_option=False,
        preserve_checked=False,
        extra_builder=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Upload Options"))
        self.path_edit = self.add_path_row(
            self.tr("Select Upload Folder"),
            self.tr("Select Upload Folder"),
            initial_path,
            placeholder,
        )
        if hint_text:
            hint = self.add_label(hint_text)
            hint.setWordWrap(True)
        self.preserve_checkbox = None
        if preserve_option:
            self.preserve_checkbox = self.add_checkbox(
                self.tr("Preserve existing annotations"),
                checked=preserve_checked,
            )
        if extra_builder is not None:
            extra_builder(self)
        self.add_buttons()

    def folder(self) -> str:
        return self.path_edit.text().strip()

    @property
    def preserve_existing(self) -> bool:
        return bool(
            self.preserve_checkbox and self.preserve_checkbox.isChecked()
        )

    def validate(self):
        if not self.folder():
            return self.tr("Upload folder path cannot be empty!")
        return ""


class UploadConfirmDialog(QtWidgets.QMessageBox):
    """Warning shown before existing annotations are overwritten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        self.setWindowTitle(self.tr("Warning"))
        self.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Cancel
            | QtWidgets.QMessageBox.StandardButton.Ok
        )
        self.setStyleSheet(get_msg_box_style())

    def ask_annotations(self, preserve_existing) -> bool:
        if preserve_existing:
            self.setText(
                self.tr("New annotations will be merged with existing ones")
            )
            self.setInformativeText(
                self.tr(
                    "You are going to add new annotations to this task. "
                    "Existing annotations will be preserved. Continue?"
                )
            )
        else:
            self.setText(self.tr("Current annotation will be lost"))
            self.setInformativeText(
                self.tr(
                    "You are going to upload new annotations to this task. "
                    "Continue?"
                )
            )
        return self.exec() == QtWidgets.QMessageBox.StandardButton.Ok

    def ask_labels(self) -> bool:
        self.setText(self.tr("Current labels will be lost"))
        self.setInformativeText(
            self.tr(
                "You are going to upload new labels to this task. Continue?"
            )
        )
        return self.exec() == QtWidgets.QMessageBox.StandardButton.Ok


class UploadCategorySection(QtWidgets.QWidget):
    """Per-class "include + score threshold" rows (MM-GD upload).

    Lives in a widget class so ``self.tr`` is registered under the same
    context the runtime uses.
    """

    def __init__(self, class_names, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel(self.tr("Category Settings")))

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(200)
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)

        self._rows = {}
        for class_name in class_names:
            row_layout = QtWidgets.QHBoxLayout()
            checkbox = QtWidgets.QCheckBox(class_name)
            checkbox.setChecked(True)
            threshold_input = QtWidgets.QDoubleSpinBox()
            threshold_input.setRange(0.0, 1.0)
            threshold_input.setSingleStep(0.01)
            threshold_input.setValue(0.20)
            threshold_input.setDecimals(2)
            row_layout.addWidget(checkbox)
            row_layout.addStretch()
            row_layout.addWidget(QtWidgets.QLabel(self.tr("Threshold:")))
            row_layout.addWidget(threshold_input)
            scroll_layout.addLayout(row_layout)
            self._rows[class_name] = (checkbox, threshold_input)

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

    def selected(self):
        """Return ``[(class_name, threshold), ...]`` for checked rows."""

        return [
            (name, threshold.value())
            for name, (checkbox, threshold) in self._rows.items()
            if checkbox.isChecked()
        ]


class UploadProgressDialog(QtWidgets.QProgressDialog):
    """Busy/progress dialog shared by the upload flows."""

    def __init__(self, parent=None, *, maximum=0, label_text=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Progress"))
        self.setLabelText(label_text or self.tr("Uploading..."))
        self.setCancelButtonText(self.tr("Cancel"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(500)
        self.setMinimumHeight(150)
        if maximum and maximum > 0:
            self.setRange(0, int(maximum))
        else:
            self.setRange(0, 0)
        self.setStyleSheet(get_progress_dialog_style())
