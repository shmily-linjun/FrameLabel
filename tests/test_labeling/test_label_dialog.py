"""Offscreen tests for the object-edit dialog (LabelDialog, fork.33)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from anylabeling.views.labeling.widgets.label_dialog import LabelDialog


class LabelDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def setUp(self):
        self.dialog = LabelDialog(labels=["cat"])

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_dialog_has_a_window_title(self):
        self.assertEqual(self.dialog.windowTitle(), "Object Edit")

    def test_clicking_the_only_class_fills_the_class_field(self):
        # The single item is already current; currentItemChanged does not
        # fire for a click on the current item, so the click signal must fill
        # the field on its own.
        self.dialog.label_list.setCurrentRow(0)
        self.dialog.edit.clear()

        self.dialog.label_list.itemClicked.emit(
            self.dialog.label_list.item(0)
        )

        self.assertEqual(self.dialog.edit.text(), "cat")


if __name__ == "__main__":
    unittest.main()
