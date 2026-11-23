"""Dialog for batch image-tag operations (fork.32/fork.37).

The file-list context menu opens it; ``FileListController.set_tags_rows()``
owns the actual write.  Keeping the dialog separate makes the batch rules
testable without a window.

Three operations are supported:

* add one or more tags to every selected image;
* replace a specific existing tag with a new tag (other tags are preserved);
* delete every image tag from the selected images.

The dialog uses the host's translation function so its strings live in the
same ``LabelingWidget`` translation context as the rest of the file list.
"""

from PyQt6 import QtWidgets

from ..utils.batch_tags import MODE_ADD, MODE_DELETE_ALL, MODE_REPLACE
from ..utils.image_tags import normalize_image_tags
from ..utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
    get_settings_combo_style,
)


class BatchTagsDialog(QtWidgets.QDialog):
    """Ask which batch tag operation to run and on which tags."""

    def __init__(
        self,
        image_count,
        library_tags=(),
        parent=None,
        translate=None,
    ):
        super().__init__(parent)
        self._tr = translate if translate is not None else self.tr
        self._image_count = image_count
        self._library_tags = normalize_image_tags(list(library_tags or ()))
        self.setWindowTitle(self._tr("Batch Set Image Tags"))
        self.setModal(True)
        self.setMinimumWidth(440)
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

        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.setStyleSheet(get_settings_combo_style())
        self.mode_combo.addItem(
            self._tr("Add to existing tags"), MODE_ADD
        )
        self.mode_combo.addItem(
            self._tr("Replace a specific tag"), MODE_REPLACE
        )
        self.mode_combo.addItem(
            self._tr("Delete all image tags"), MODE_DELETE_ALL
        )
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.stack = QtWidgets.QStackedWidget(self)
        self.stack.addWidget(self._build_add_page())
        self.stack.addWidget(self._build_replace_page())
        self.stack.addWidget(self._build_delete_page())
        layout.addWidget(self.stack)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("QLabel { color: #DE350B; }")
        layout.addWidget(self.error_label)

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

    # -- pages ---------------------------------------------------------
    def _build_add_page(self):
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(
            QtWidgets.QLabel(self._tr("Tags to add (comma separated)"))
        )
        self.tags_edit = QtWidgets.QLineEdit(page)
        self.tags_edit.setPlaceholderText(self._tr("tag1, tag2"))
        self.tags_edit.setClearButtonEnabled(True)
        layout.addWidget(self.tags_edit)
        layout.addWidget(self._make_library_picker(self.tags_edit, page))
        return page

    def _build_replace_page(self):
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QtWidgets.QLabel(self._tr("Tag to replace")))
        self.old_tag_combo = QtWidgets.QComboBox(page)
        self.old_tag_combo.setStyleSheet(get_settings_combo_style())
        self.old_tag_combo.setEditable(True)
        self.old_tag_combo.addItems(self._library_tags)
        self.old_tag_combo.setCurrentIndex(-1)
        if self.old_tag_combo.lineEdit() is not None:
            self.old_tag_combo.lineEdit().setPlaceholderText(
                self._tr("Select or type the tag to replace")
            )
        layout.addWidget(self.old_tag_combo)
        layout.addWidget(
            QtWidgets.QLabel(self._tr("Replace with (comma separated)"))
        )
        self.new_tags_edit = QtWidgets.QLineEdit(page)
        self.new_tags_edit.setPlaceholderText(self._tr("tag1, tag2"))
        self.new_tags_edit.setClearButtonEnabled(True)
        layout.addWidget(self.new_tags_edit)
        layout.addWidget(
            self._make_library_picker(self.new_tags_edit, page)
        )
        return page

    def _build_delete_page(self):
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        warning = QtWidgets.QLabel(
            self._tr("This removes every image tag from %d images.")
            % self._image_count
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        return page

    def _make_library_picker(self, target_edit, parent):
        combo = QtWidgets.QComboBox(parent)
        combo.setStyleSheet(get_settings_combo_style())
        combo.addItem(self._tr("Add from tag library…"), None)
        for tag in self._library_tags:
            combo.addItem(tag, tag)
        combo.activated.connect(
            lambda _index, widget=combo, edit=target_edit: (
                self._append_library_tag(widget, edit)
            )
        )
        return combo

    def _append_library_tag(self, combo, edit):
        tag = combo.currentData()
        if tag:
            parts = [part.strip() for part in edit.text().split(",")]
            parts = [part for part in parts if part]
            parts.append(str(tag))
            edit.setText(", ".join(parts))
            edit.setFocus()
        combo.setCurrentIndex(0)

    # -- mode / validation --------------------------------------------
    def _on_mode_changed(self, index):
        self.stack.setCurrentIndex(index)
        self.error_label.clear()

    def mode(self):
        return self.mode_combo.currentData()

    def tags(self):
        """Return the normalized tags to add (or the replacement tags)."""
        if self.mode() == MODE_DELETE_ALL:
            return []
        edit = (
            self.new_tags_edit
            if self.mode() == MODE_REPLACE
            else self.tags_edit
        )
        return self._parse_tags(edit.text())

    def old_tags(self):
        """Return the existing tag(s) to remove in replace mode."""
        if self.mode() != MODE_REPLACE:
            return []
        return self._parse_tags(self.old_tag_combo.currentText())

    def replace(self):
        """Compatibility helper: whether the replace mode is selected."""
        return self.mode() == MODE_REPLACE

    def accept(self):
        self.error_label.clear()
        if not self._validate():
            return
        super().accept()

    def _validate(self):
        mode = self.mode()
        if mode == MODE_DELETE_ALL:
            return True
        if mode == MODE_ADD and not self.tags():
            self.error_label.setText(
                self._tr("Enter at least one tag.")
            )
            return False
        if mode == MODE_REPLACE:
            if not self.old_tags():
                self.error_label.setText(
                    self._tr("Select the tag to replace.")
                )
                return False
            if not self.tags():
                self.error_label.setText(
                    self._tr("Enter the replacement tag.")
                )
                return False
        return True

    @staticmethod
    def _parse_tags(text):
        parts = [part.strip() for part in text.replace("\n", ",").split(",")]
        return normalize_image_tags([part for part in parts if part])
