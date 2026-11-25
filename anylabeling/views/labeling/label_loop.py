"""Guided label loop for fast repeated annotation.

The loop walks the object list, offers the next label in a popup and
lets the user accept or skip shapes with a few keys.  It used to be
part of ``LabelingWidget``.
"""

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from .utils.label_text import measure_text_width
from .utils.qt import new_icon_path
from .widgets.popup import Popup

# pylupdate6 only records `tr()` calls inside class bodies.  These
# modules also translate text through `host.tr`/`self.tr` in free
# functions and helpers, where the receiver is the LabelingWidget; the
# constant tells `scripts/translation_scan.py` which context to use
# (see docs/dev/CODE_STRUCTURE_REPORT.md).
TR_CONTEXT = "LabelingWidget"


def _find_next_label_loop_shape(shapes, start_index, canvas_shapes):
    """Return the next shape of ``shapes`` that is still on the canvas.

    Deleted shapes can stay in the label-list snapshot; identity (``id``)
    is used rather than equality so equal-but-distinct shapes are kept.
    """
    canvas_shape_ids = {id(shape) for shape in canvas_shapes}
    for index in range(start_index, len(shapes)):
        shape = shapes[index]
        if id(shape) in canvas_shape_ids:
            return index, shape
    return len(shapes), None


class LabelLoop:
    """Review loop over the object list."""

    def __init__(self, host):
        self.host = host

    def _reset_label_loop(self):
        self.host.label_loop_count = -1
        self.host.label_loop_shapes = None
        if self.host.label_loop_popup is not None:
            self.host.label_loop_popup.close()

    def _show_label_loop_popup(self, text):
        if self.host.label_loop_popup is None:
            self.host.label_loop_popup = Popup(
                text,
                parent=self.host,
                msec=1800,
                icon=new_icon_path("copy-green", "svg"),
            )
            self.host.label_loop_popup.label.setTextFormat(Qt.TextFormat.PlainText)
            self.host.label_loop_popup.setAttribute(
                Qt.WidgetAttribute.WA_ShowWithoutActivating
            )
            self.host.label_loop_popup.setWindowFlag(
                Qt.WindowType.WindowDoesNotAcceptFocus, True
            )
            self.host.label_loop_popup.setWindowFlag(
                Qt.WindowType.WindowTransparentForInput, True
            )
        else:
            self.host.label_loop_popup.set_text(text)
        self.host.label_loop_popup.show_popup(
            self.host.central_widget().viewport(), top_offset=24
        )

    def loop_thru_labels(self):
        is_new_loop = self.host.label_loop_shapes is None
        if is_new_loop:
            self.host.label_loop_shapes = list(self.host.canvas.shapes)

        self.host.label_loop_count, shape = _find_next_label_loop_shape(
            self.host.label_loop_shapes,
            self.host.label_loop_count + 1,
            self.host.canvas.shapes,
        )
        if shape is None:
            message = (
                self.host.tr("No objects to review")
                if is_new_loop
                else self.host.tr("Review complete")
            )
            self.host._reset_label_loop()
            if not is_new_loop:
                self.host.canvas.deselect_shape()
                self.host.set_fit_window()
            self.host._show_label_loop_popup(message)
            return

        width = self.host.central_widget().width() - 2.0
        height = self.host.central_widget().height() - 2.0

        im_width = self.host.canvas.pixmap.width()
        im_height = self.host.canvas.pixmap.height()

        zoom_scale = 4

        xs = []
        ys = []
        # loop through all points on this label
        for point in shape.points:
            xs.append(point.x())
            ys.append(point.y())

        # Set minimum label width to 30px this should handle point
        # lables and very tiny labels gracefully
        label_width = max(int(max(xs) - min(xs)), 30)
        x = (max(xs) + min(xs)) / 2
        y = (max(ys) + min(ys)) / 2

        zoom = int(100 * width / (zoom_scale * label_width))
        # Don't go past the max zoom which is 1000
        zoom = min(1000, zoom)

        self.host.set_zoom(zoom)
        self.host.canvas.pan_offset = QtCore.QPointF()
        self.host.pan_values[self.host.filename] = QtCore.QPointF()

        x_range = self.host.scroll_bars[Qt.Orientation.Horizontal].maximum()
        x_step = self.host.scroll_bars[Qt.Orientation.Horizontal].pageStep()

        y_range = self.host.scroll_bars[Qt.Orientation.Vertical].maximum()
        # QT docs says Document length = maximum() - minimum() + pageStep().
        # so there's a weird pageStep thing we gotta add
        y_step = self.host.scroll_bars[Qt.Orientation.Vertical].pageStep()
        screen_width = width / (zoom / 100)
        # add half a screen to this
        x_scroll = int((x - screen_width / 2) / im_width * (x_range + x_step))
        x_scroll = min(max(0, x_scroll), x_range)

        screen_height = height / (zoom / 100)

        y_scroll = int(
            (y - screen_height / 2) / (im_height) * (y_range + y_step)
        )
        y_scroll = min(max(0, y_scroll), y_range)

        self.host.set_scroll(Qt.Orientation.Horizontal, x_scroll)
        self.host.set_scroll(Qt.Orientation.Vertical, y_scroll)
        self.host.canvas.prev_h_shape = self.host.canvas.h_shape = shape
        self.host.canvas.select_shapes([shape])

        progress = self.host.tr("Reviewing {current} / {total}").format(
            current=self.host.label_loop_count + 1,
            total=len(self.host.label_loop_shapes),
        )
        font_metrics = self.host.fontMetrics()
        label_width = min(
            240,
            max(
                0,
                self.host.central_widget().viewport().width()
                - measure_text_width(font_metrics, progress)
                - 56,
            ),
        )
        label = font_metrics.elidedText(
            str(shape.label or ""), Qt.TextElideMode.ElideRight, label_width
        )
        if label:
            progress = f"{progress} - {label}"
        self.host._show_label_loop_popup(progress)

    def loop_select_labels(self):
        self.host.select_loop_count += 1
        if len(self.host.label_list) == 0 or self.host.select_loop_count >= len(
            self.host.label_list
        ):
            self.host.select_loop_count = -1
            self.host.canvas.deselect_shape()
            return

        item = self.host.label_list[self.host.select_loop_count]
        shape = item.shape()
        self.host.canvas.select_shapes([shape])

    def copy_to_clipboard(self, text):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(
            self.host,
            self.host.tr("Copied"),
            self.host.tr("The information has been copied to the clipboard."),
        )
