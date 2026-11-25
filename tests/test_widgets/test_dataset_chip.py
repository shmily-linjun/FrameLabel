"""Offscreen tests for the title-bar dataset chip (fork.56)."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from anylabeling.views.labeling.widgets.dataset_chip import (  # noqa: E402
    DatasetChip,
)


@pytest.fixture()
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _registry(entries):
    return SimpleNamespace(list=lambda: entries)


def _entry(name, root, state="active"):
    return SimpleNamespace(
        display_name=name,
        root_path=root,
        db_path=os.path.join(root, "xanylabeling.db"),
        state=state,
        uuid="uuid-" + name,
    )


def _actions(menu):
    return [action for action in menu.actions() if not action.isSeparator()]


def test_chip_without_dataset_offers_the_center(app):
    chip = DatasetChip(registry_provider=lambda: _registry([]))
    try:
        assert chip.text() == "No dataset"
        chip._rebuild_menu()
        texts = [action.text() for action in _actions(chip.menu())]
        assert "Dataset Center…" in texts
        close = next(
            action for action in _actions(chip.menu()) if action.text() == "Close dataset"
        )
        assert not close.isEnabled()
        switch = next(
            action
            for action in _actions(chip.menu())
            if action.text() == "Switch dataset"
        )
        assert not switch.isEnabled() or switch.menu() is not None
        empty = [
            action
            for action in switch.menu().actions()
            if action.text() == "No other datasets"
        ]
        assert empty and not empty[0].isEnabled()
    finally:
        chip.deleteLater()


def test_chip_shows_name_and_switches(app):
    entries = [
        _entry("Same", "C:/data/first"),
        _entry("Same", "C:/data/second"),
    ]
    chip = DatasetChip(registry_provider=lambda: _registry(entries))
    emitted = []
    chip.open_dataset_requested.connect(emitted.append)
    try:
        chip.set_dataset("Same", "C:/data/first")
        assert chip.text() == "Dataset: Same"
        assert "first" in chip.toolTip()
        chip._rebuild_menu()
        switch = next(
            action
            for action in _actions(chip.menu())
            if action.text() == "Switch dataset"
        )
        labels = [action.text() for action in switch.menu().actions()]
        assert labels == ["Same"]
        switch.menu().actions()[0].trigger()
        assert emitted == ["C:/data/second"]
        close = next(
            action for action in _actions(chip.menu()) if action.text() == "Close dataset"
        )
        assert close.isEnabled()
    finally:
        chip.deleteLater()


def test_chip_close_signal(app):
    chip = DatasetChip(registry_provider=lambda: _registry([]))
    closed = []
    chip.close_dataset_requested.connect(lambda: closed.append(True))
    try:
        chip.set_dataset("Demo", "C:/data/demo")
        chip._rebuild_menu()
        close = next(
            action for action in _actions(chip.menu()) if action.text() == "Close dataset"
        )
        close.trigger()
        assert closed == [True]
    finally:
        chip.deleteLater()
