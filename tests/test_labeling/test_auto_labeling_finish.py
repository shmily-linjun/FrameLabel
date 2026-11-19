"""Regression tests for finishing SAM/auto-labeling objects.

The reported crash was ``AttributeError: 'NoneType' object has no attribute
'setText'`` in ``LabelingWidget.finish_auto_labeling_object``: a second
auto-labeling result in "add" mode removed the placeholder's object-list row
but kept the shape on the canvas, so the finish step found a shape without a
row.
"""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.auto_labeling.types import (
    AutoLabelingMode,
    AutoLabelingResult,
)
from anylabeling.services.identity.store import Operator
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    window = MainWindow(app, config=copy.deepcopy(load_template_config()))
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    yield window
    window.labeling_widget.view.dirty = False
    window.close()
    app.removeEventFilter(window.labeling_widget.view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _object_shape(x):
    shape = Shape(label=AutoLabelingMode.OBJECT, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, 20.0),
        QtCore.QPointF(x + 40.0, 60.0),
    ]
    shape.close()
    return shape


def _open_image(window, tmp_path):
    view = window.labeling_widget.view
    path = tmp_path / "image.png"
    image = QtGui.QImage(
        QtCore.QSize(320, 240), QtGui.QImage.Format.Format_RGB32
    )
    image.fill(QtGui.QColor("#808080"))
    image.save(str(path))
    assert view.load_file(str(path))
    view.operator_service.session.login(
        Operator(id=1, name="tester", is_admin=True)
    )
    # Answer the label dialog with the last used label.
    view._config["auto_use_last_label"] = True
    view._config["auto_use_last_gid"] = False
    view.label_dialog.add_label_history("cat")
    return view


def test_second_auto_labeling_result_leaves_no_orphan_placeholder(
    window, tmp_path
):
    view = _open_image(window, tmp_path)
    view.new_shapes_from_auto_labeling(
        AutoLabelingResult([_object_shape(10)], replace=False)
    )
    view.new_shapes_from_auto_labeling(
        AutoLabelingResult([_object_shape(100)], replace=False)
    )

    placeholders = [
        shape
        for shape in view.canvas.shapes
        if shape.label == AutoLabelingMode.OBJECT
    ]
    assert len(placeholders) == 1
    assert view.label_list.find_item_by_shape(placeholders[0]) is not None


def test_finish_object_labels_the_placeholder(window, tmp_path):
    view = _open_image(window, tmp_path)
    view.new_shapes_from_auto_labeling(
        AutoLabelingResult([_object_shape(10)], replace=False)
    )
    view.new_shapes_from_auto_labeling(
        AutoLabelingResult([_object_shape(100)], replace=False)
    )

    view.finish_auto_labeling_object()

    assert [shape.label for shape in view.canvas.shapes] == ["cat"]
    texts = [
        view.label_list.item(row).text()
        for row in range(view.label_list.count())
    ]
    assert texts == ["cat"]


def test_finish_object_adopts_a_placeholder_without_a_row(
    window, tmp_path
):
    view = _open_image(window, tmp_path)
    orphan = _object_shape(200)
    view.canvas.shapes.append(orphan)
    orphan.cache_label = "cat"
    assert view.label_list.find_item_by_shape(orphan) is None

    view.finish_auto_labeling_object()

    assert view.label_list.find_item_by_shape(orphan) is not None
    assert orphan.label == "cat"
