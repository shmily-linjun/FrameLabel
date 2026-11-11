"""Lock / visibility semantics that survive the plain-list refactor.

The objects/classes tabs no longer paint per-row checkboxes, lock icons or a
panel header with show/hide and lock-all buttons. The underlying session-lock
policy is still used by the label manager dialog and the bulk lock helpers are
kept, so those are covered here. Plain-list rendering itself is covered by
``tests/test_widgets`` and the labeling smoke tests.
"""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

import anylabeling.resources.resources  # noqa: F401

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.label_list_widget import (
    LOCKED_ROLE,
)
from anylabeling.views.labeling.widgets.unique_label_qlist_widget import (
    UniqueLabelQListWidget,
)


class TestLabelLocks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def setUp(self):
        self.labels = UniqueLabelQListWidget()
        for label in ("cat", "dog"):
            item = self.labels.create_item_from_label(label)
            self.labels.addItem(item)
            self.labels.set_item_label(item, label)
        self.shapes = [Shape(label=label) for label in ("cat", "cat", "dog")]
        self.widget = SimpleNamespace(
            unique_label_list=self.labels,
            canvas=SimpleNamespace(shapes=self.shapes),
            _update_shapes_lock=Mock(),
            refresh_panel_controls=Mock(),
            _session_shape_locks={},
        )
        self.widget.toggle_unique_label_items_lock = (
            LabelingWidget.toggle_unique_label_items_lock.__get__(
                self.widget
            )
        )
        self.widget._set_shapes_locked = (
            LabelingWidget._set_shapes_locked.__get__(self.widget)
        )

    def tearDown(self):
        self.labels.close()

    def test_plain_list_has_no_checkboxes_or_lock_icon(self):
        for item in (
            self.labels.item(0),
            self.labels.item(1),
        ):
            self.assertIsNone(item.data(QtCore.Qt.ItemDataRole.CheckStateRole))
            self.assertFalse(item.data(LOCKED_ROLE))
            self.assertFalse(
                bool(item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            )

    def test_find_and_remove_items_by_label(self):
        found = self.labels.find_items_by_label("cat")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].text(), "cat")
        self.labels.remove_items_by_label("cat")
        self.assertFalse(self.labels.find_items_by_label("cat"))
        self.assertTrue(self.labels.find_items_by_label("dog"))

    def test_bulk_inverts_mixed_categories(self):
        LabelingWidget.toggle_unique_label_items_lock(
            self.widget, [self.labels.item(0)]
        )
        LabelingWidget.toggle_unique_label_items_lock(
            self.widget, [self.labels.item(0), self.labels.item(1)]
        )
        self.assertEqual([s.locked for s in self.shapes], [False, False, True])

    def test_empty_category_keeps_policy_when_list_is_rebuilt(self):
        self.widget.canvas.shapes = []
        LabelingWidget.toggle_unique_label_items_lock(
            self.widget, [self.labels.item(0)]
        )
        self.widget._update_shapes_lock.assert_not_called()
        self.labels.clear()
        item = self.labels.create_item_from_label("cat")
        self.labels.addItem(item)
        self.labels.set_item_label(item, "cat")
        self.assertTrue(self.labels.lock_states["cat"])
        self.assertTrue(item.data(LOCKED_ROLE))

    def test_bulk_labels_replaces_previous_individual_lock(self):
        LabelingWidget.toggle_unique_label_items_lock(
            self.widget, [self.labels.item(0)]
        )
        for expected in (False, True, False):
            LabelingWidget.toggle_all_labels_lock(self.widget)
            self.assertEqual([s.locked for s in self.shapes], [expected] * 3)
            self.assertEqual(
                self.labels.lock_states,
                {"cat": expected, "dog": expected},
            )

    def test_bulk_shapes_clears_previous_category_policy(self):
        LabelingWidget.toggle_unique_label_items_lock(
            self.widget, [self.labels.item(0)]
        )
        for expected in (False, True, False):
            LabelingWidget.toggle_all_shapes_lock(self.widget)
            self.assertEqual([s.locked for s in self.shapes], [expected] * 3)
            self.assertEqual(self.labels.lock_states, {})
            self.assertFalse(self.labels.item(0).data(LOCKED_ROLE))

    def test_object_locks_survive_image_switch_in_memory(self):
        from anylabeling.views.labeling.widgets.label_list_widget import (
            LabelListWidget,
            LabelListWidgetItem,
        )

        self.widget.image_path = "/tmp/session-image.png"
        self.widget._shape_lock_key = LabelingWidget._shape_lock_key
        self.shapes[0].locked = True
        LabelingWidget._remember_shape_locks(self.widget)
        restored = [
            Shape().load_from_dict(shape.to_dict()) for shape in self.shapes
        ]
        objects = LabelListWidget()
        for shape in restored:
            objects.add_iem(LabelListWidgetItem(shape.label, shape))
        self.widget.canvas.shapes = restored
        self.widget.label_list = objects
        LabelingWidget._restore_shape_locks(self.widget)
        self.assertEqual([s.locked for s in restored], [True, False, False])
        self.widget._session_shape_locks.clear()
        for shape in restored:
            shape.locked = False
        LabelingWidget._restore_shape_locks(self.widget)
        self.assertFalse(any(s.locked for s in restored))
        objects.close()

    def test_locking_does_not_mark_annotations_dirty(self):
        self.widget.label_list = Mock()
        self.widget.canvas.store_shapes = Mock()
        self.widget.canvas.update = Mock()
        self.widget.canvas.editing = Mock(return_value=False)
        self.widget.refresh_shape_lock_action = Mock()
        self.widget.set_dirty = Mock()
        LabelingWidget._update_shapes_lock(self.widget, self.shapes)
        self.widget.set_dirty.assert_not_called()


if __name__ == "__main__":
    unittest.main()
