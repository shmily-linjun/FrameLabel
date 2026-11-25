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
from ..widgets.tag_library import TagLibraryWidget


class BatchTagsDialog(QtWidgets.QDialog):
    """Ask which batch tag operation to run and on which tags."""

    def __init__(
        self,
        image_count,
        library_tags=(),
        parent=None,
    ):
        super().__init__(parent)
        self._image_count = image_count
        self._library_tags = normalize_image_tags(list(library_tags or ()))
        self.setWindowTitle(self.tr("Batch Set Image Tags"))
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(get_dialog_style())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        layout.addWidget(
            QtWidgets.QLabel(
                self.tr("Apply tags to the selected images (%d):")
                % image_count
            )
        )

        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.setStyleSheet(get_settings_combo_style())
        self.mode_combo.addItem(
            self.tr("Add to existing tags"), MODE_ADD
        )
        self.mode_combo.addItem(
            self.tr("Replace a specific tag"), MODE_REPLACE
        )
        self.mode_combo.addItem(
            self.tr("Delete all image tags"), MODE_DELETE_ALL
        )
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.add_page = self._build_add_page()
        self.replace_page = self._build_replace_page()
        self.delete_page = self._build_delete_page()
        layout.addWidget(self.add_page)
        layout.addWidget(self.replace_page)
        layout.addWidget(self.delete_page)
        self.replace_page.hide()
        self.delete_page.hide()

        self.library_widget = TagLibraryWidget(self)
        self.library_widget.set_entries(
            [(tag, 0) for tag in self._library_tags], []
        )
        self.library_widget.set_editing_enabled(True)
        self.library_widget.list_widget.setMinimumHeight(60)
        self.library_widget.tag_clicked.connect(self._append_library_tag)
        layout.addWidget(self.library_widget, 1)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("QLabel { color: #DE350B; }")
        layout.addWidget(self.error_label)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QtWidgets.QPushButton(self.tr("Cancel"))
        cancel_button.setStyleSheet(get_cancel_btn_style())
        cancel_button.clicked.connect(self.reject)
        ok_button = QtWidgets.QPushButton(self.tr("OK"))
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
        layout.setSpacing(4)
        layout.addWidget(
            QtWidgets.QLabel(self.tr("Tags to add (comma separated)"))
        )
        self.tags_edit = QtWidgets.QLineEdit(page)
        self.tags_edit.setPlaceholderText(self.tr("tag1, tag2"))
        self.tags_edit.setClearButtonEnabled(True)
        layout.addWidget(self.tags_edit)
        return page

    def _build_replace_page(self):
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QtWidgets.QLabel(self.tr("Tag to replace")))
        self.old_tag_combo = QtWidgets.QComboBox(page)
        self.old_tag_combo.setStyleSheet(get_settings_combo_style())
        self.old_tag_combo.setEditable(True)
        self.old_tag_combo.addItems(self._library_tags)
        self.old_tag_combo.setCurrentIndex(-1)
        if self.old_tag_combo.lineEdit() is not None:
            self.old_tag_combo.lineEdit().setPlaceholderText(
                self.tr("Select or type the tag to replace")
            )
        layout.addWidget(self.old_tag_combo)
        layout.addWidget(
            QtWidgets.QLabel(self.tr("Replace with (comma separated)"))
        )
        self.new_tags_edit = QtWidgets.QLineEdit(page)
        self.new_tags_edit.setPlaceholderText(self.tr("tag1, tag2"))
        self.new_tags_edit.setClearButtonEnabled(True)
        layout.addWidget(self.new_tags_edit)
        return page

    def _build_delete_page(self):
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        warning = QtWidgets.QLabel(
            self.tr("This removes every image tag from %d images.")
            % self._image_count
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        return page

    def _append_library_tag(self, tag):
        if not tag:
            return
        edit = (
            self.new_tags_edit
            if self.mode() == MODE_REPLACE
            else self.tags_edit
        )
        parts = [part.strip() for part in edit.text().split(",")]
        parts = [part for part in parts if part]
        parts.append(str(tag))
        edit.setText(", ".join(parts))
        edit.setFocus()

    # -- mode / validation --------------------------------------------
    def _on_mode_changed(self, index):
        mode = self.mode()
        self.add_page.setVisible(mode == MODE_ADD)
        self.replace_page.setVisible(mode == MODE_REPLACE)
        self.delete_page.setVisible(mode == MODE_DELETE_ALL)
        self.library_widget.setVisible(mode != MODE_DELETE_ALL)
        self.error_label.clear()
        self.adjustSize()

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
                self.tr("Enter at least one tag.")
            )
            return False
        if mode == MODE_REPLACE:
            if not self.old_tags():
                self.error_label.setText(
                    self.tr("Select the tag to replace.")
                )
                return False
            if not self.tags():
                self.error_label.setText(
                    self.tr("Enter the replacement tag.")
                )
                return False
        return True

    @staticmethod
    def _parse_tags(text):
        parts = [part.strip() for part in text.replace("\n", ",").split(",")]
        return normalize_image_tags([part for part in parts if part])
