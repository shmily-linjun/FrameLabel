"""Shared chrome for the labeling window's option dialogs (fork.49).

Qt extracts translatable strings from ``*.tr(...)`` calls that are written
inside a class body, and looks them up at runtime with the *object's* class
name.  For dialogs created by free helper functions both sides used to
diverge, so their text never reached the ``.ts`` files.  The rule that keeps
them aligned is:

* text owned by the base class uses an explicit
  ``QCoreApplication.translate("BaseDialog", ...)`` call (a base method runs
  with the subclass name at runtime, so ``self.tr`` would register the wrong
  context);
* text owned by a dialog uses ``self.tr(...)`` inside that dialog's methods;
* ``other_widget.tr(...)`` is not used, because the extractor would record
  the enclosing class while the runtime looks up the other widget's class.

The guard test ``tests/test_i18n`` enforces these rules.
"""

from PyQt6 import QtWidgets
from PyQt6.QtCore import QCoreApplication

from ..utils.style import (
    get_cancel_btn_style,
    get_export_option_style,
    get_ok_btn_style,
)


class BaseDialog(QtWidgets.QDialog):
    """Base class for the option dialogs of the labeling window.

    Subclasses build their body with :meth:`add_path_row`,
    :meth:`add_checkbox`, :meth:`add_widget` and finish with
    :meth:`add_buttons`; :meth:`validate` can veto ``accept()``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(500)
        self.setStyleSheet(get_export_option_style())
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(24, 24, 24, 24)
        self.body.setSpacing(16)
        self.path_edit = None

    # -- body helpers ------------------------------------------------------
    def add_widget(self, widget):
        self.body.addWidget(widget)
        return widget

    def add_label(self, text):
        return self.add_widget(QtWidgets.QLabel(text))

    def add_path_row(
        self,
        label_text,
        browse_title,
        initial_path="",
        placeholder="",
        parent=None,
    ):
        """Add a "label + path edit + Browse" row and return the edit."""

        container = QtWidgets.QVBoxLayout()
        container.addWidget(QtWidgets.QLabel(label_text))

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        edit = QtWidgets.QLineEdit()
        edit.setText(str(initial_path or ""))
        if placeholder:
            edit.setPlaceholderText(placeholder)
        if parent is None:
            parent = self

        def browse():
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                parent,
                browse_title,
                edit.text(),
                QtWidgets.QFileDialog.Option.ShowDirsOnly
                | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
            )
            if chosen:
                edit.setText(chosen)

        button = QtWidgets.QPushButton(
            QCoreApplication.translate("BaseDialog", "Browse")
        )
        button.clicked.connect(browse)
        button.setStyleSheet(get_cancel_btn_style())

        row.addWidget(edit)
        row.addWidget(button)
        container.addLayout(row)
        self.body.addLayout(container)
        self.path_edit = edit
        return edit

    def add_checkbox(self, text, checked=False):
        checkbox = QtWidgets.QCheckBox(text)
        checkbox.setChecked(checked)
        self.body.addWidget(checkbox)
        return checkbox

    def add_buttons(self, on_accept=None):
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setContentsMargins(0, 16, 0, 0)
        button_layout.setSpacing(8)

        cancel_button = QtWidgets.QPushButton(
            QCoreApplication.translate("BaseDialog", "Cancel")
        )
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet(get_cancel_btn_style())

        ok_button = QtWidgets.QPushButton(
            QCoreApplication.translate("BaseDialog", "OK")
        )
        ok_button.clicked.connect(
            self.accept if on_accept is None else on_accept
        )
        ok_button.setStyleSheet(get_ok_btn_style())

        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        self.body.addLayout(button_layout)

    # -- validation --------------------------------------------------------
    def validate(self):
        """Return an error message to keep the dialog open, or ``""``."""

        return ""

    def accept(self):  # noqa: N802 - Qt naming
        error = self.validate()
        if error:
            QtWidgets.QMessageBox.warning(
                self,
                QCoreApplication.translate("BaseDialog", "Warning"),
                error,
            )
            return
        super().accept()
