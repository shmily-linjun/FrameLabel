"""Regression tests for the main window's toolbar state handling.

The window state written by older builds could contain a *floating* toolbar.
Qt restores that floating flag even when the toolbar is not floatable, and the
restored geometry then makes Windows resize the floating window to huge sizes
(QWindowsWindow::setGeometry warnings, CreateDIBSection failures). The window
therefore persists its toolbar area explicitly and drops the legacy
``window/state`` key.
"""

import copy
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow

_TOOLBAR_STATE_MARKER = 0xFC
_DOCK_STATE_MARKER = 0xFD


def _pack_rect(x, y, w, h):
    geom0 = ((w & 0xFFFF) << 16) | ((x + 0x7FFF) & 0xFFFF)
    geom1 = ((h & 0xFFFF) << 16) | ((y + 0x7FFF) & 0xFFFF)
    return ((geom0 << 1) | 1) & 0xFFFFFFFF, geom1 & 0xFFFFFFFF


def _make_floating_toolbar_state(app, rect=(0, 0, 640, 200)):
    """Return QMainWindow state bytes that mark ToolsToolBar as floating."""
    window = QtWidgets.QMainWindow()
    toolbar = QtWidgets.QToolBar("Tools")
    toolbar.setObjectName("ToolsToolBar")
    toolbar.setFloatable(False)
    toolbar.addAction("a")
    window.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
    state = bytearray(window.saveState())
    window.close()
    window.deleteLater()
    app.processEvents()

    position = 8  # quint32 magic + int stream version
    while position < len(state):
        marker = state[position]
        position += 1
        if marker == _DOCK_STATE_MARKER:
            count = struct.unpack_from(">i", state, position)[0]
            position += 4
            assert count == 0, "test fixture has no dock widgets"
            position += 8 + 16  # central widget QSize + four corner ints
        elif marker == _TOOLBAR_STATE_MARKER:
            line_count = struct.unpack_from(">i", state, position)[0]
            position += 4
            for _ in range(line_count):
                position += 4  # toolbar area
                item_count = struct.unpack_from(">i", state, position)[0]
                position += 4
                for _ in range(item_count):
                    name_length = struct.unpack_from(">I", state, position)[0]
                    name = bytes(
                        state[position + 4 : position + 4 + name_length]
                    ).decode("utf-16-be")
                    position += 4 + name_length
                    shown_offset = position
                    position += 1 + 4 + 4 + 4 + 4
                    if name != "ToolsToolBar":
                        continue
                    state[shown_offset] = 1  # visible, horizontal
                    geom0, geom1 = _pack_rect(*rect)
                    struct.pack_into(">I", state, shown_offset + 9, geom0)
                    struct.pack_into(">I", state, shown_offset + 13, geom1)
            return bytes(state)
        else:
            raise AssertionError(f"unexpected state marker {marker:#x}")
    raise AssertionError("toolbar state marker not found")


class _WindowFactory:
    """Build MainWindow instances sharing one INI settings file."""

    def __init__(self, app, tmp_path, monkeypatch):
        self.app = app
        self.windows = []
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        config_file = tmp_path / "config.yaml"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            app_config, "current_config_file", str(config_file)
        )
        self.ini_path = str(tmp_path / "settings.ini")
        settings_class = QtCore.QSettings
        monkeypatch.setattr(
            QtCore,
            "QSettings",
            lambda *args, **kwargs: settings_class(
                self.ini_path, settings_class.Format.IniFormat
            ),
        )

    def make(self):
        window = MainWindow(
            self.app, config=copy.deepcopy(load_template_config())
        )
        window.resize(1600, 1000)
        self.windows.append(window)
        return window

    def settings(self):
        return QtCore.QSettings()

    def close(self, window):
        if window not in self.windows:
            return
        self.windows.remove(window)
        window.labeling_widget.view.dirty = False
        window.close()
        self.app.removeEventFilter(window.labeling_widget.view)
        window.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.fixture
def factory():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return app


@pytest.fixture
def window_factory(factory, tmp_path, monkeypatch):
    builder = _WindowFactory(factory, tmp_path, monkeypatch)
    yield builder
    for window in builder.windows:
        builder.close(window)


def _toolbar(window):
    return window.findChild(QtWidgets.QToolBar, "ToolsToolBar")


def test_legacy_floating_state_is_discarded(window_factory):
    app = window_factory.app
    settings = window_factory.settings()
    settings.setValue(
        "window/state",
        QtCore.QByteArray(_make_floating_toolbar_state(app)),
    )
    settings.sync()

    window = window_factory.make()
    window.show()
    app.processEvents()

    toolbar = _toolbar(window)
    assert toolbar is not None
    assert not toolbar.isFloating()
    assert (
        window.toolBarArea(toolbar)
        == QtCore.Qt.ToolBarArea.TopToolBarArea
    )
    assert not window.settings.contains("window/state")


def test_toolbar_area_is_persisted(window_factory):
    app = window_factory.app
    window = window_factory.make()
    window.show()
    app.processEvents()
    window.dock_toolbar(QtCore.Qt.ToolBarArea.LeftToolBarArea)
    assert window.settings.value("window/toolbar_area") == "left"
    window_factory.close(window)

    second = window_factory.make()
    second.show()
    app.processEvents()
    toolbar = _toolbar(second)
    assert (
        second.toolBarArea(toolbar)
        == QtCore.Qt.ToolBarArea.LeftToolBarArea
    )
    assert not toolbar.isFloating()


def test_close_does_not_save_window_state(window_factory):
    app = window_factory.app
    window = window_factory.make()
    window.show()
    app.processEvents()
    window_factory.close(window)
    assert not window.settings.contains("window/state")
    assert window.settings.value("window/toolbar_area") == "top"


def test_toolbar_visibility_is_persisted(window_factory):
    app = window_factory.app
    window = window_factory.make()
    window.show()
    app.processEvents()
    window.set_toolbar_visible(False)
    window_factory.close(window)

    second = window_factory.make()
    second.show()
    app.processEvents()
    assert not _toolbar(second).isVisible()
