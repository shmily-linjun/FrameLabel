"""Tests for the label manager panel hosted by the "Classes" tab."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.widgets.label_manager import (
    LabelManagerPanel,
)
from anylabeling.views.labeling.widgets.unique_label_qlist_widget import (
    UniqueLabelQListWidget,
)


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


if __name__ == "__main__":
    unittest.main()
