"""Regression test for the file dialog preview (fork.59)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from anylabeling.views.labeling.widgets.file_dialog_preview import (
    FileDialogPreview,
)


@pytest.fixture()
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_preview_dialog_has_a_layout(app):
    dialog = FileDialogPreview(
        None, "Open", ".", "All Files (*)"
    )
    try:
        assert dialog.testOption(
            QtWidgets.QFileDialog.Option.DontUseNativeDialog
        )
        assert dialog.layout() is not None
        assert dialog.label_preview.isHidden()
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_open_file_builds_the_dialog_without_crashing(app, monkeypatch):
    """The reported crash happened while constructing the dialog."""

    from anylabeling.views.labeling import file_session as module

    host = QtWidgets.QWidget()
    host.filename = ""
    host.last_open_dir = ""
    host.output_dir = None
    host.dataset_repository = None
    host.may_continue = lambda: True
    monkeypatch.setattr(
        module.FileDialogPreview, "exec", lambda self: 0
    )
    try:
        module.FileSession(host).open_file()
    finally:
        host.deleteLater()
        app.processEvents()
