"""Tests for the native file-dialog helpers (fork.60)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from anylabeling.views.file_dialogs import (
    choose_directory,
    choose_open_file,
    choose_open_files,
    choose_save_file,
)


@pytest.fixture()
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _native(options):
    return not (
        options & QtWidgets.QFileDialog.Option.DontUseNativeDialog
    )


def test_choose_open_file_is_native(app, monkeypatch):
    seen = {}

    def fake(parent, title, directory, filters, options=0):
        seen["options"] = options
        return ("C:/data/a.png", "Images")

    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", fake
    )
    assert choose_open_file(None, "Open", "C:/data", "Images (*.png)") == (
        "C:/data/a.png"
    )
    assert _native(seen["options"])


def test_choose_open_files_is_native(app, monkeypatch):
    seen = {}

    def fake(parent, title, directory, filters, options=0):
        seen["options"] = options
        return (["C:/a.png", "C:/b.png"], "Images")

    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileNames", fake
    )
    assert choose_open_files(None, "Open", "", "Images (*.png)") == [
        "C:/a.png",
        "C:/b.png",
    ]
    assert _native(seen["options"])


def test_choose_directory_and_save_are_native(app, monkeypatch):
    seen = []

    def fake_directory(parent, title, directory, options=0):
        seen.append(("directory", options))
        return "C:/data"

    def fake_save(parent, title, directory, filters, options=0):
        seen.append(("save", options))
        return ("C:/data/a.json", "Labels")

    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getExistingDirectory", fake_directory
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", fake_save
    )
    assert choose_directory(None, "Pick") == "C:/data"
    assert choose_save_file(None, "Save", "C:/data", "Labels (*.json)") == (
        "C:/data/a.json"
    )
    assert all(_native(options) for _kind, options in seen)


def test_cancel_returns_empty_values(app, monkeypatch):
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: ("", "")
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getExistingDirectory", lambda *a, **k: ""
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: ("", "")
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileNames", lambda *a, **k: ([], "")
    )
    assert choose_open_file(None, "t") == ""
    assert choose_directory(None, "t") == ""
    assert choose_save_file(None, "t") == ""
    assert choose_open_files(None, "t") == []


def test_open_file_uses_the_helper(app, monkeypatch):
    from anylabeling.views.labeling import file_session as module

    host = QtWidgets.QWidget()
    host.filename = ""
    host.last_open_dir = ""
    host.may_continue = lambda: True
    host._clear_file_list = lambda: None
    loaded = []
    host.load_file = loaded.append
    seen = {}
    monkeypatch.setattr(
        module,
        "choose_open_file",
        lambda parent, title, directory, filters: (
            seen.update(title=title, filters=filters) or "C:/a.png"
        ),
    )
    try:
        module.FileSession(host).open_file()
    finally:
        host.deleteLater()
        app.processEvents()
    assert loaded == ["C:/a.png"]
    assert ".json" in seen["filters"]


def test_save_file_dialog_uses_the_helper(app, monkeypatch):
    from anylabeling.views.labeling import file_session as module

    host = QtWidgets.QWidget()
    host.filename = "C:/data/a.png"
    host.output_dir = None
    host.dataset_repository = None
    host.current_path = lambda: "C:/data"
    seen = {}
    monkeypatch.setattr(
        module,
        "choose_save_file",
        lambda parent, title, directory, filters: (
            seen.update(directory=directory, filters=filters)
            or "C:/data/a.json"
        ),
    )
    try:
        result = module.FileSession(host).save_file_dialog()
    finally:
        host.deleteLater()
        app.processEvents()
    assert result == "C:/data/a.json"
    assert seen["directory"].endswith("a.json")
    assert "json" in seen["filters"]
