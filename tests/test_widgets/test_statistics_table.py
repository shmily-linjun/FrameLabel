"""Offscreen tests for the statistics table widget."""

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

from anylabeling.views.labeling.utils.dataset_statistics import (  # noqa: E402
    COLUMN_HEADERS,
    OBJECTLESS_ROW_LABEL,
    SPLIT_NONE,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
    TOTAL_ROW_LABEL,
    ClassSplitTable,
    FileStatisticsEntry,
    StatisticsFilter,
)
from anylabeling.views.labeling.widgets.statistics_table import (  # noqa: E402
    StatisticsTable,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORK_ROOT = _REPO_ROOT / "temporary" / "pytest-statistics-widgets"


def _make_entries():
    return [
        FileStatisticsEntry("a.jpg", SPLIT_TRAIN, ("car", "person"), True),
        FileStatisticsEntry("b.jpg", SPLIT_VAL, ("person",), True),
        FileStatisticsEntry("c.jpg", SPLIT_NONE, (), True),
    ]


def _make_work_dir():
    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    directory = _WORK_ROOT / uuid.uuid4().hex
    directory.mkdir()
    return directory


def _remove_work_dir(directory):
    shutil.rmtree(directory, ignore_errors=True)
    try:
        _WORK_ROOT.rmdir()
    except OSError:
        pass


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)


class StatisticsTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def setUp(self):
        self.widget = StatisticsTable(entries=_make_entries())
        self.filters = []
        self.widget.filter_requested.connect(self.filters.append)

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    # -- helpers -------------------------------------------------------
    def _click_cell(self, row, column):
        self.widget.cellClicked.emit(row, column)

    def _click_header(self, section):
        self.widget.horizontalHeader().sectionClicked.emit(section)

    def _texts(self):
        return [
            [
                self.widget.item(row, column).text()
                for column in range(self.widget.columnCount())
            ]
            for row in range(self.widget.rowCount())
        ]

    # -- structure -----------------------------------------------------
    def test_headers_and_row_labels(self):
        assert self.widget.columnCount() == len(COLUMN_HEADERS)
        headers = [
            self.widget.horizontalHeaderItem(column).text()
            for column in range(self.widget.columnCount())
        ]
        assert headers == list(COLUMN_HEADERS)
        assert headers[0] == "Class"
        assert headers[-1] == "Total"

        assert self.widget.rowCount() == 4
        assert self.widget.verticalHeader().isHidden()
        assert self._texts()[0][0] == "car"
        assert self._texts()[1][0] == "person"
        assert self._texts()[2][0] == OBJECTLESS_ROW_LABEL
        assert self._texts()[3][0] == TOTAL_ROW_LABEL

    def test_counts_rendered(self):
        # Bottom row values are *file* counts per split (the two classes in
        # "a.jpg" both live in the train split, which still counts as 1 file),
        # and the bottom-right cell is the total number of images.
        assert self._texts() == [
            ["car", "1", "0", "0", "0", "1"],
            ["person", "1", "1", "0", "0", "2"],
            [OBJECTLESS_ROW_LABEL, "0", "0", "0", "1", "1"],
            [TOTAL_ROW_LABEL, "1", "1", "0", "1", "3"],
        ]
        statistics = self.widget.statistics
        assert statistics.split_totals[SPLIT_TRAIN] == 1
        assert statistics.class_totals == {"car": 1, "person": 2}
        assert statistics.total == 3
        assert statistics.total == statistics.entry_count

    def test_empty_table_still_renders(self):
        widget = StatisticsTable()
        try:
            assert widget.rowCount() == 2
            assert widget.item(0, 0).text() == OBJECTLESS_ROW_LABEL
            assert widget.item(1, 0).text() == TOTAL_ROW_LABEL
            for column in range(1, widget.columnCount()):
                assert widget.item(0, column).text() == "0"
                assert widget.item(1, column).text() == "0"
            assert widget.statistics.entry_count == 0
        finally:
            widget.close()
            widget.deleteLater()

    def test_read_only_and_single_row_selection(self):
        view = QtWidgets.QAbstractItemView
        assert (
            self.widget.editTriggers()
            == view.EditTrigger.NoEditTriggers
        )
        assert (
            self.widget.selectionBehavior()
            == view.SelectionBehavior.SelectRows
        )
        assert (
            self.widget.selectionMode()
            == view.SelectionMode.SingleSelection
        )
        assert not (
            self.widget.item(1, 2).flags()
            & Qt.ItemFlag.ItemIsEditable
        )

    def test_theme_stylesheet_is_applied(self):
        assert self.widget.objectName() == "StatisticsTable"
        assert "StatisticsTable" in self.widget.styleSheet()
        assert "QHeaderView::section" in self.widget.styleSheet()

    # -- click payloads ------------------------------------------------
    def test_numeric_cell_emits_label_and_split(self):
        self._click_cell(0, 1)
        self._click_cell(1, 2)
        assert self.filters == [
            StatisticsFilter(label="car", split=SPLIT_TRAIN),
            StatisticsFilter(label="person", split=SPLIT_VAL),
        ]

    def test_class_name_cell_emits_label_only(self):
        self._click_cell(1, 0)
        assert self.filters == [
            StatisticsFilter(label="person", split=None)
        ]

    def test_split_header_emits_split_only(self):
        self._click_header(1)
        self._click_header(3)
        self._click_header(4)
        assert self.filters == [
            StatisticsFilter(split=SPLIT_TRAIN),
            StatisticsFilter(split=SPLIT_TEST),
            StatisticsFilter(split=SPLIT_NONE),
        ]

    def test_objectless_cells(self):
        objectless_row = len(self.widget.statistics.classes)
        self._click_cell(objectless_row, 1)
        self._click_cell(objectless_row, 0)
        assert self.filters == [
            StatisticsFilter(split=SPLIT_TRAIN, objectless=True),
            StatisticsFilter(split=None, objectless=True),
        ]

    def test_totals_are_not_clickable(self):
        total_row = len(self.widget.statistics.classes) + 1
        for column in range(self.widget.columnCount()):
            self._click_cell(total_row, column)
        # totals column of every class/objectless row
        for row in range(total_row):
            self._click_cell(row, 5)
        # class-name header and totals header
        self._click_header(0)
        self._click_header(5)
        assert self.filters == []

    def test_cell_filter_api(self):
        assert self.widget.cell_filter(0, 1) == StatisticsFilter(
            label="car", split=SPLIT_TRAIN
        )
        assert self.widget.cell_filter(0, 0) == StatisticsFilter(
            label="car", split=None
        )
        assert self.widget.cell_filter(0, 5) is None
        assert self.widget.cell_filter(3, 1) is None
        assert self.widget.cell_filter(-1, 1) is None
        assert self.widget.cell_filter(0, 99) is None
        assert self.widget.header_filter(1) == StatisticsFilter(
            split=SPLIT_TRAIN
        )
        assert self.widget.header_filter(0) is None
        assert self.widget.header_filter(5) is None

    # -- data refresh --------------------------------------------------
    def test_set_entries_returns_table(self):
        table = self.widget.set_entries(_make_entries())
        assert isinstance(table, ClassSplitTable)
        assert table.classes == ("car", "person")
        assert self.widget.statistics is table

    def test_refresh_reads_annotation_files(self):
        directory = _make_work_dir()
        try:
            images = directory / "images"
            images.mkdir()
            labels = directory / "labels"
            labels.mkdir()
            train_image = images / "train.jpg"
            val_image = images / "val.jpg"
            _write_json(
                labels / "train.json",
                {"split": "train", "shapes": [{"label": "person"}]},
            )
            _write_json(
                labels / "val.json",
                {"split": "test", "shapes": [{"label": "car"}]},
            )
            # Adjacent annotations that must be ignored when output_dir is set.
            for image_name in ("train.json", "val.json"):
                _write_json(
                    images / image_name,
                    {
                        "split": "none",
                        "shapes": [{"label": "adjacent"}],
                    },
                )

            table = self.widget.refresh(
                [str(train_image), str(val_image)], str(labels)
            )

            assert table.classes == ("car", "person")
            assert table.count_for("person", SPLIT_TRAIN) == 1
            assert table.count_for("car", SPLIT_TEST) == 1
            assert table.objectless_total == 0
            assert table.split_totals[SPLIT_TRAIN] == 1
            assert table.split_totals[SPLIT_TEST] == 1
            assert table.total == 2
            assert table.entry_count == 2
            assert self.widget.statistics is table
        finally:
            _remove_work_dir(directory)


if __name__ == "__main__":
    unittest.main()
