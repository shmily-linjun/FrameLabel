"""Dialog for applying one tag list to several selected images (fork.32).

The file-list context menu opens it; ``FileListController.set_tags_rows()``
owns the actual write.  Keeping the dialog separate makes the batch rule
testable without a window (see :mod:`...utils.batch_tags`).

The dialog uses the host's translation function so its strings live in the
same ``LabelingWidget`` translation context as the rest of the file list.
"""

from PyQt6 import QtWidgets

from ..utils.image_tags import normalize_image_tags
from ..utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
    get_settings_combo_style,
)

#: Combo data values for the two batch modes.
MODE_ADD = "add"
MODE_REPLACE = "replace"


class BatchTagsDialog(QtWidgets.QDialog):
    """Ask for a tag list and whether to add or replace existing tags."""

    def __init__(self, image_count, parent=None, translate=None):
        super().__init__(parent)
        self._tr = translate if translate is not None else self.tr
        self.setWindowTitle(self._tr("Set Image Tags"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(get_dialog_style())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(
            QtWidgets.QLabel(
                self._tr("Apply tags to the selected images (%d):")
                % image_count
            )
        )
        layout.addWidget(
            QtWidgets.QLabel(self._tr("Tags (comma separated)"))
        )
        self.tags_edit = QtWidgets.QLineEdit(self)
        self.tags_edit.setPlaceholderText(self._tr("tag1, tag2"))
        self.tags_edit.setClearButtonEnabled(True)
        layout.addWidget(self.tags_edit)

        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.setStyleSheet(get_settings_combo_style())
        self.mode_combo.addItem(
            self._tr("Add to existing tags"), MODE_ADD
        )
        self.mode_combo.addItem(
            self._tr("Replace existing tags"), MODE_REPLACE
        )
        layout.addWidget(self.mode_combo)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QtWidgets.QPushButton(self._tr("Cancel"))
        cancel_button.setStyleSheet(get_cancel_btn_style())
        cancel_button.clicked.connect(self.reject)
        ok_button = QtWidgets.QPushButton(self._tr("OK"))
        ok_button.setStyleSheet(get_ok_btn_style())
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)
        layout.addLayout(buttons)

        self.tags_edit.setFocus()

    def tags(self):
        """Return the normalized tags typed by the user."""
        text = self.tags_edit.text().replace("\n", ",")
        parts = [part.strip() for part in text.split(",")]
        return normalize_image_tags([part for part in parts if part])

    def replace(self):
        """Whether the typed tags replace the existing ones."""
        return self.mode_combo.currentData() == MODE_REPLACE
