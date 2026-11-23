"""Tests for the label manager panel hosted by the "Classes" tab."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtTest import QTest

from anylabeling.views.labeling.widgets.label_manager import (
    REFRESH_DELAY_MS,
    LabelManagerPanel,
)
from anylabeling.views.labeling.widgets.unique_label_qlist_widget import (
    UniqueLabelQListWidget,
)


class FakeCategoryRepository:
    """Minimal repository surface used by the "Classes" tab."""

    def __init__(self, names):
        self.names = list(names)

    def category_counts(self):
        return [
            {"name": name, "object_count": 1}
            for name in self.names
        ]

    def set_category_order(self, names):
        names = list(names)
        if not names or any(name not in self.names for name in names):
            return False
        self.names = names
        return True


class PanelHost(QtWidgets.QWidget):
    """Minimal ``LabelingWidget`` surface used by the panel."""

    def __init__(self, files):
        super().__init__()
        self.file_list_widget = QtWidgets.QListWidget()
        for path in files:
            self.file_list_widget.addItem(str(path))
        self.unique_label_list = UniqueLabelQListWidget()
        self.label_info = {}
        self.output_dir = None
        self.filename = str(files[0]) if files else None
        self.loaded_file = None
        self.visibility_calls = 0
        self.label_dialog = Mock()

    def _get_rgb_by_label(self, label, skip_label_info=False):
        return (0, 255, 0)

    def apply_label_visibility(self):
        self.visibility_calls += 1

    def _refresh_statistics_if_visible(self):
        pass

    def load_file(self, filename):
        self.loaded_file = filename

    def tr(self, text):
        return text

    def status(self, *_args, **_kwargs):
        pass


class TestLabelManagerPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.paths = []
        for index in range(2):
            image = Path(self.temp.name) / f"{index}.png"
            label_path = image.with_suffix(".json")
            label_path.write_text(
                json.dumps(
                    {
                        "shapes": [
                            {"label": "cat", "points": [[0, 0]]},
                            {"label": "dog", "points": [[1, 1]]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.paths.append(label_path)
        files = [path.with_suffix(".png") for path in self.paths]
        self.host = PanelHost(files)
        self.panel = LabelManagerPanel(self.host)
        self.panel.set_editing_enabled(True)
        self.panel.ensure_built()

    def tearDown(self):
        self.panel.close()
        self.host.close()
        self.temp.cleanup()

    # -- helpers -------------------------------------------------------
    def row_of(self, label):
        for row in range(self.panel.table.rowCount()):
            if self.panel.table.item(row, 0).text() == label:
                return row
        raise AssertionError(f"{label} row not found")

    def labels_of(self, path):
        return [
            shape["label"]
            for shape in json.loads(path.read_text(encoding="utf-8"))[
                "shapes"
            ]
        ]

    def apply(self, start=1, end=None):
        self.panel.from_input.setValue(start)
        self.panel.to_input.setValue(
            self.panel.to_input.maximum() if end is None else end
        )
        with patch(
            "anylabeling.views.labeling.widgets.label_manager.Popup"
        ):
            self.panel.apply_changes()

    # -- tests ---------------------------------------------------------
    def test_rows_show_categories_of_all_files(self):
        labels = [
            self.panel.table.item(row, 0).text()
            for row in range(self.panel.table.rowCount())
        ]
        self.assertEqual(labels, ["cat", "dog"])
        self.assertEqual(self.panel.from_input.maximum(), 2)
        self.assertEqual(self.panel.to_input.value(), 2)

    def test_range_controls_match_reorder_button_height(self):
        self.assertEqual(self.panel.from_input.height(), 22)
        self.assertEqual(self.panel.to_input.height(), 22)
        self.assertEqual(self.panel.range_button.height(), 22)
        self.assertEqual(self.panel.move_up_button.height(), 22)
        self.assertLessEqual(self.panel.range_button.width(), 48)

    def test_lock_only_updates_session_policy(self):
        before = [path.read_bytes() for path in self.paths]
        lock = self.panel._checkbox(self.row_of("cat"), 3)
        lock.setChecked(True)
        self.apply(start=1, end=1)
        self.assertEqual([path.read_bytes() for path in self.paths], before)
        self.assertTrue(self.host.unique_label_list.lock_states["cat"])
        self.assertIsNone(self.host.loaded_file)
        self.assertEqual(self.host.visibility_calls, 1)

    def test_explicit_unlock_does_not_rewrite_json(self):
        before = [path.read_bytes() for path in self.paths]
        lock = self.panel._checkbox(self.row_of("cat"), 3)
        lock.setChecked(True)
        lock.setChecked(False)
        self.apply(start=1, end=2)
        self.assertEqual([path.read_bytes() for path in self.paths], before)
        self.assertFalse(self.host.unique_label_list.lock_states["cat"])

    def test_rename_applies_only_inside_the_range(self):
        item = self.panel.table.item(self.row_of("cat"), 0)
        item.setText("feline")
        self.apply(start=1, end=1)
        self.assertEqual(self.labels_of(self.paths[0]), ["feline", "dog"])
        self.assertEqual(self.labels_of(self.paths[1]), ["cat", "dog"])
        self.assertEqual(self.host.loaded_file, self.host.filename)

    def test_rename_is_applied_to_every_row_in_the_range(self):
        item = self.panel.table.item(self.row_of("dog"), 0)
        item.setText("hound")
        self.apply(start=1, end=2)
        for path in self.paths:
            self.assertEqual(self.labels_of(path), ["cat", "hound"])

    def test_delete_applies_only_inside_the_range(self):
        delete = self.panel._checkbox(self.row_of("dog"), 1)
        delete.setChecked(True)
        self.apply(start=1, end=1)
        self.assertEqual(self.labels_of(self.paths[0]), ["cat"])
        self.assertEqual(self.labels_of(self.paths[1]), ["cat", "dog"])

    def test_duplicate_rename_is_rejected_without_writing(self):
        before = [path.read_bytes() for path in self.paths]
        item = self.panel.table.item(self.row_of("cat"), 0)
        item.setText("dog")
        self.apply(start=1, end=2)
        self.assertEqual([path.read_bytes() for path in self.paths], before)

    def test_empty_rename_is_rejected(self):
        before = [path.read_bytes() for path in self.paths]
        item = self.panel.table.item(self.row_of("cat"), 0)
        item.setText("   ")
        self.apply(start=1, end=2)
        # Empty text is read back as "no rename", not as a file write.
        self.assertEqual([path.read_bytes() for path in self.paths], before)

    def test_apply_requires_logged_in_operator(self):
        before = [path.read_bytes() for path in self.paths]
        self.panel.set_editing_enabled(False)
        item = self.panel.table.item(self.row_of("cat"), 0)
        item.setText("feline")
        self.apply(start=1, end=2)
        self.assertEqual([path.read_bytes() for path in self.paths], before)

    def test_delete_disables_category_editing(self):
        self.panel.resize(600, 300)
        self.panel.show()
        self.app.processEvents()
        row = self.row_of("cat")
        checkbox = self.panel._checkbox(row, 1)
        container = self.panel.table.cellWidget(row, 1)
        self.assertTrue(checkbox.icon().isNull())
        self.assertLessEqual(
            abs(
                checkbox.geometry().center().x()
                - container.rect().center().x()
            ),
            1,
        )
        checkbox.setChecked(True)
        item = self.panel.table.item(row, 0)
        self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)

    def test_selected_label_returns_current_category(self):
        self.panel.table.setCurrentCell(self.row_of("dog"), 0)
        self.assertEqual(self.panel.selected_label(), "dog")
        self.panel._checkbox(self.row_of("dog"), 1).setChecked(True)
        self.assertIsNone(self.panel.selected_label())

    def test_invalidate_rebuilds_after_new_label(self):
        self.panel.invalidate()
        self.panel.ensure_built()
        self.assertEqual(self.panel.table.rowCount(), 2)

    # -- database order ------------------------------------------------
    def row_labels(self):
        return [
            self.panel.table.item(row, 0).text()
            for row in range(self.panel.table.rowCount())
        ]

    def test_rows_follow_the_database_category_order(self):
        self.host.dataset_repository = FakeCategoryRepository(
            ["dog", "cat"]
        )
        self.panel.invalidate()
        self.panel.ensure_built()
        self.assertEqual(self.row_labels(), ["dog", "cat"])

    def test_categories_without_objects_are_not_listed(self):
        repository = FakeCategoryRepository(["cat", "dog"])
        repository.category_counts = lambda: [
            {"name": "cat", "object_count": 2},
            {"name": "dog", "object_count": 0},
        ]
        self.host.dataset_repository = repository
        self.panel.invalidate()
        self.panel.ensure_built()
        self.assertEqual(self.row_labels(), ["cat"])

    def test_move_up_persists_the_new_order(self):
        repository = FakeCategoryRepository(["cat", "dog"])
        self.host.dataset_repository = repository
        self.panel.invalidate()
        self.panel.ensure_built()
        self.panel.table.setCurrentCell(self.row_of("dog"), 0)
        self.assertTrue(self.panel.move_up_button.isEnabled())
        self.panel.move_up_button.click()
        self.assertEqual(repository.names, ["dog", "cat"])
        self.assertEqual(self.row_labels(), ["dog", "cat"])
        self.assertEqual(self.panel._selected_category(), "dog")

    def test_move_down_persists_the_new_order(self):
        repository = FakeCategoryRepository(["cat", "dog"])
        self.host.dataset_repository = repository
        self.panel.invalidate()
        self.panel.ensure_built()
        self.panel.table.setCurrentCell(self.row_of("cat"), 0)
        self.panel.move_down_button.click()
        self.assertEqual(repository.names, ["dog", "cat"])
        self.assertEqual(self.row_labels(), ["dog", "cat"])

    def test_reorder_requires_a_dataset_database(self):
        self.panel.table.setCurrentCell(self.row_of("dog"), 0)
        self.assertFalse(self.panel.move_up_button.isEnabled())
        self.assertFalse(self.panel.move_down_button.isEnabled())
        self.assertIn(
            "dataset database",
            self.panel.move_up_button.toolTip(),
        )


class TestLabelManagerLiveRefresh(unittest.TestCase):
    """The visible "Classes" tab follows category changes without a click."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.image = Path(self.temp.name) / "image.png"
        self.label = self.image.with_suffix(".json")
        self.write_labels(["cat"])
        self.host = PanelHost([self.image])
        self.host.right_tabs = QtWidgets.QTabWidget()
        self.host.right_tabs.addTab(QtWidgets.QWidget(), "Objects")
        # Match the real workspace: the panel sits inside a rounded container
        # that is the tab page, so visibility must follow the ancestor chain.
        self.page = QtWidgets.QWidget()
        page_layout = QtWidgets.QVBoxLayout(self.page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = LabelManagerPanel(self.host)
        page_layout.addWidget(self.panel)
        self.host.right_tabs.addTab(self.page, "Classes")
        self.host.right_tabs.setCurrentWidget(self.page)
        self.panel.set_editing_enabled(True)
        self.panel.ensure_built()

    def tearDown(self):
        self.panel.close()
        self.host.close()
        self.temp.cleanup()

    def write_labels(self, labels):
        self.label.write_text(
            json.dumps(
                {
                    "shapes": [
                        {"label": label, "points": [[0, 0]]}
                        for label in labels
                    ]
                }
            ),
            encoding="utf-8",
        )

    def labels_of_table(self):
        return [
            self.panel.table.item(row, 0).text()
            for row in range(self.panel.table.rowCount())
        ]

    def test_visible_tab_refreshes_after_a_category_change(self):
        self.write_labels(["cat", "dog"])
        self.panel.invalidate()
        QTest.qWait(REFRESH_DELAY_MS + 120)
        self.app.processEvents()
        self.assertEqual(self.labels_of_table(), ["cat", "dog"])

    def test_hidden_tab_only_refreshes_when_activated(self):
        self.write_labels(["cat", "dog"])
        self.host.right_tabs.setCurrentIndex(0)
        self.panel.invalidate()
        QTest.qWait(REFRESH_DELAY_MS + 120)
        self.app.processEvents()
        self.assertEqual(self.labels_of_table(), ["cat"])
        self.panel.ensure_built()
        self.assertEqual(self.labels_of_table(), ["cat", "dog"])

    def test_live_refresh_keeps_the_selected_range(self):
        self.write_labels(["cat"])
        self.panel.from_input.setValue(1)
        self.panel.to_input.setValue(1)
        self.write_labels(["cat", "dog"])
        self.panel.invalidate()
        self.panel.flush_refresh()
        self.assertEqual(self.panel.from_input.value(), 1)
        self.assertEqual(self.panel.to_input.value(), 1)


if __name__ == "__main__":
    unittest.main()
