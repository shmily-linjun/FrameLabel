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
        self.widget = TagLibraryWidget()
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

    def test_the_whole_vocabulary_stays_listed(self):
        assert self._item_texts() == ["defect", "scratch", "blur"]
        assert self.widget.count_label.text() == "(3)"

    def test_header_search_is_readable_and_count_follows_title(self):
        assert self.widget.search_edit.height() >= 24
        assert (
            self.widget.count_label.x()
            >= self.widget.title_label.x()
            + self.widget.title_label.width()
        )
        assert self.widget.search_edit.x() > self.widget.count_label.x()

    def test_search_filters_the_list(self):
        self.widget.search_edit.setText("blu")
        assert self._item_texts() == ["blur"]
        assert self.widget.count_label.text() == "(3)"

        self.widget.search_edit.setText("zzz")
        assert self._item_texts() == []
        assert self.widget.empty_label.text() == "No matching tags."
        assert self.widget.empty_label.isVisible() is True

    def test_single_click_does_not_add(self):
        item = self.widget.list_widget.item(0)
        self.widget.list_widget.itemClicked.emit(item)
        self.app.processEvents()
        assert self.clicked == []

    def test_double_click_adds(self):
        item = self.widget.list_widget.item(1)
        self.widget.list_widget.itemDoubleClicked.emit(item)
        self.app.processEvents()
        assert self.clicked == ["scratch"]
        assert self.searches == []

    def test_double_click_on_an_applied_tag_is_a_no_op(self):
        statuses = []
        self.widget.status_message.connect(statuses.append)
        item = self.widget.list_widget.item(0)
        self.widget.list_widget.itemDoubleClicked.emit(item)
        self.app.processEvents()
        assert self.clicked == []
        assert statuses == ["This tag is already on the image."]

    def test_long_tag_is_not_truncated_to_a_tiny_cell(self):
        self.widget.set_entries(
            [("这是一个比较长的标签名称", 1)], current_tags=[]
        )
        item = self.widget.list_widget.item(0)
        assert item.sizeHint().width() >= 96
        assert item.sizeHint().width() <= 200

    def test_ctrl_click_requests_a_tag_search(self):
        self.widget._is_search_gesture = lambda: True
        item = self.widget.list_widget.item(1)
        self.widget.list_widget.itemClicked.emit(item)
        self.app.processEvents()
        assert self.searches == ["scratch"]
        assert self.clicked == []

    def test_applied_tags_remain_searchable(self):
        # The applied tag stays in the list, so its right-click search still
        # works (fork.58 motivation).
        self.widget._is_search_gesture = lambda: True
        item = self.widget.list_widget.item(0)
        self.widget.list_widget.itemClicked.emit(item)
        self.app.processEvents()
        assert self.searches == ["defect"]

    def test_collapse_hides_the_body(self):
        self.widget.set_collapsed(True)
        assert self.widget.is_collapsed() is True
        assert self.widget.body.isVisible() is False
        self.widget.set_collapsed(False)
        assert self.widget.body.isVisible() is True


if __name__ == "__main__":
    unittest.main()
