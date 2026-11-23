"""Offscreen tests for the Image Attributes tag library (fork.34)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from anylabeling.views.labeling.widgets.tag_library import (
    TagLibraryWidget,
)


class TagLibraryWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def setUp(self):
        self.widget = TagLibraryWidget(translate=lambda text: text)
        self.widget.resize(280, 260)
        self.widget.show()
        self.app.processEvents()
        self.widget.set_entries(
            [("defect", 3), ("scratch", 2), ("blur", 1)],
            current_tags=["defect"],
        )
        self.clicked = []
        self.searches = []
        self.widget.tag_clicked.connect(self.clicked.append)
        self.widget.tag_search_requested.connect(self.searches.append)

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def _item_texts(self):
        return [
            self.widget.list_widget.item(index).text()
            for index in range(self.widget.list_widget.count())
        ]

    def test_only_missing_tags_are_listed(self):
        assert self._item_texts() == ["scratch", "blur"]
        assert self.widget.count_label.text() == "(2)"

    def test_search_filters_the_list(self):
        self.widget.search_edit.setText("blu")
        assert self._item_texts() == ["blur"]
        assert self.widget.count_label.text() == "(2)"

        self.widget.search_edit.setText("zzz")
        assert self._item_texts() == []
        assert self.widget.empty_label.text() == "No matching tags."
        assert self.widget.empty_label.isVisible() is True

    def test_click_emits_after_event_loop(self):
        item = self.widget.list_widget.item(0)
        self.widget.list_widget.itemClicked.emit(item)
        assert self.clicked == []
        self.app.processEvents()
        assert self.clicked == ["scratch"]

    def test_ctrl_click_requests_a_tag_search(self):
        self.widget._is_search_gesture = lambda: True
        item = self.widget.list_widget.item(0)
        self.widget.list_widget.itemClicked.emit(item)
        self.app.processEvents()
        assert self.searches == ["scratch"]
        assert self.clicked == []

    def test_collapse_hides_the_body(self):
        self.widget.set_collapsed(True)
        assert self.widget.is_collapsed() is True
        assert self.widget.body.isVisible() is False
        self.widget.set_collapsed(False)
        assert self.widget.body.isVisible() is True


if __name__ == "__main__":
    unittest.main()
