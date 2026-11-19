"""Zoom, pan, fit-to-window and navigator behaviour of the canvas.

The canvas itself handles mouse and geometry editing; this class owns the
viewport state around it: tracked zoom/pan per file, the animation of zoom
steps, scroll bar synchronisation, fit-window/fit-width and the overview
navigator dialog. It used to live on ``LabelingWidget``.

The host (``LabelingWidget``) owns the canvas, scroll area, zoom widget,
navigator dialog and the per-file view state maps; this class is stateless and
only reads/mutates the host.
"""

import math
from typing import Optional

from PyQt6 import QtCore, QtGui

from .widgets.navigator_widget import NavigatorDialog


class CanvasNavigation:
    """Viewport state and navigator commands for the labeling canvas."""

    def __init__(self, host):
        self.host = host

    def restore_navigator_state(self) -> None:
        try:
            navigator_visible: bool = self.host.settings.value(
                "navigator/visible", False, type=bool
            )

            if navigator_visible:
                self.host.navigator_dialog.show()

                if hasattr(self.host, "image") and not self.host.image.isNull():
                    self.host.navigator_dialog.set_image(
                        QtGui.QPixmap.fromImage(self.host.image)
                    )
                    self.host.update_navigator_viewport()
                else:
                    self.host._should_restore_navigator = True

                # Restore geometry information
                geometry = self.host.settings.value("navigator/geometry")
                if geometry:
                    self.host.navigator_dialog.restoreGeometry(geometry)
                else:
                    # Fallback: restore position and size separately
                    saved_size = self.host.settings.value("navigator/size")
                    saved_position = self.host.settings.value("navigator/position")

                    if saved_size:
                        self.host.navigator_dialog.resize(saved_size)
                    if saved_position:
                        self.host.navigator_dialog.move(saved_position)

                if hasattr(self.host, "actions") and hasattr(
                    self.host.actions, "show_navigator"
                ):
                    self.host.actions.show_navigator.setChecked(True)

        except Exception as e:
            print(f"Error restoring navigator state: {e}")

    def _navigator_close_event(self, event: QtGui.QCloseEvent) -> None:
        if hasattr(self.host, "actions") and hasattr(
            self.host.actions, "show_navigator"
        ):
            self.host.actions.show_navigator.setChecked(False)

        self.host.settings.setValue("navigator/visible", False)

        NavigatorDialog.closeEvent(self.host.navigator_dialog, event)

    def on_navigator_request(self, x_ratio, y_ratio):
        """Handle navigation request from navigator widget."""
        if not hasattr(self.host, "image") or self.host.image.isNull():
            return

        image_pos = QtCore.QPointF(
            x_ratio * self.host.canvas.pixmap.width(),
            y_ratio * self.host.canvas.pixmap.height(),
        )
        canvas_pos = (
            image_pos + self.host.canvas.offset_to_center()
        ) * self.host.canvas.scale
        center = QtCore.QPointF(
            self.host._canvas_scroll_area.viewport().rect().center()
            - self.host.canvas.pos()
        )
        self.host.pan_canvas(center - canvas_pos)

    def update_navigator_viewport(self):
        """Update the viewport rectangle in the navigator."""
        if not hasattr(self.host, "navigator_dialog") or not hasattr(self.host, "image"):
            return

        if not self.host.navigator_dialog.isVisible():
            return

        if self.host.image.isNull():
            return

        scroll_area = self.host._central_widget
        canvas_size = self.host.canvas.pixmap.size() * self.host.canvas.scale
        scroll_area_size = scroll_area.viewport().size()
        if canvas_size.width() <= 0 or canvas_size.height() <= 0:
            return

        origin = self.host.canvas.transform_pos(QtCore.QPointF(-self.host.canvas.pos()))
        x_ratio = origin.x() / self.host.canvas.pixmap.width()
        y_ratio = origin.y() / self.host.canvas.pixmap.height()
        width_ratio = scroll_area_size.width() / canvas_size.width()
        height_ratio = scroll_area_size.height() / canvas_size.height()

        self.host.navigator_dialog.set_viewport(
            x_ratio, y_ratio, width_ratio, height_ratio
        )
        self.host.update_navigator_shapes()

    def update_navigator_shapes(self):
        """Update shapes overlay in navigator."""
        if (
            not hasattr(self.host, "navigator_dialog")
            or not self.host.navigator_dialog.isVisible()
        ):
            return

        shapes = getattr(self.host.canvas, "shapes", [])
        canvas_visible = getattr(self.host.canvas, "visible", {})
        h_shape = getattr(self.host.canvas, "h_shape", None)
        for shape in shapes:
            shape._is_highlighted = shape == h_shape
        self.host.navigator_dialog.set_shapes(shapes, canvas_visible)

    def on_navigator_zoom_changed(
        self, zoom_percentage: int, mouse_pos: Optional[QtCore.QPoint] = None
    ) -> None:
        """Handle zoom change from navigator controls."""

        if not hasattr(self.host, "image") or self.host.image.isNull():
            return

        if mouse_pos is not None:
            canvas_pos = self.host._convert_navigator_pos_to_canvas(mouse_pos)
            if canvas_pos is not None:
                self.host.set_zoom(zoom_percentage, pos=canvas_pos)
                return

        # Handle direct zoom changes
        self.host.set_zoom(zoom_percentage)

    def _convert_navigator_pos_to_canvas(
        self, navigator_pos: QtCore.QPoint
    ) -> Optional[QtCore.QPoint]:
        """Convert navigator mouse position to canvas coordinates."""
        if (
            not hasattr(self.host, "navigator_dialog")
            or not self.host.navigator_dialog.isVisible()
        ):
            return None

        navigator_widget = self.host.navigator_dialog.navigator
        if (
            not navigator_widget.image_rect
            or navigator_widget.image_rect.isEmpty()
        ):
            return None

        relative_x = navigator_pos.x() - navigator_widget.image_rect.x()
        relative_y = navigator_pos.y() - navigator_widget.image_rect.y()
        if (
            relative_x < 0
            or relative_x > navigator_widget.image_rect.width()
            or relative_y < 0
            or relative_y > navigator_widget.image_rect.height()
        ):
            return None

        # Convert to ratio (0.0 to 1.0)
        x_ratio = relative_x / navigator_widget.image_rect.width()
        y_ratio = relative_y / navigator_widget.image_rect.height()

        # Convert to canvas coordinates
        offset = self.host.canvas.offset_to_center()
        canvas_x = round(
            (x_ratio * self.host.canvas.pixmap.width() + offset.x())
            * self.host.canvas.scale
        )
        canvas_y = round(
            (y_ratio * self.host.canvas.pixmap.height() + offset.y())
            * self.host.canvas.scale
        )

        return QtCore.QPoint(canvas_x, canvas_y)

    def on_navigator_viewport_update_requested(self):
        """Handle viewport update request from navigator resize"""
        QtCore.QTimer.singleShot(50, self.host.update_navigator_viewport)

    def toggle_navigator(self):
        """Toggle the navigator window visibility"""
        if self.host.navigator_dialog.isVisible():
            self.host.navigator_dialog.hide()
            if hasattr(self.host, "actions") and hasattr(
                self.host.actions, "show_navigator"
            ):
                self.host.actions.show_navigator.setChecked(False)
        else:
            self.host.navigator_dialog.show()
            if hasattr(self.host, "image") and not self.host.image.isNull():
                self.host.navigator_dialog.set_image(
                    QtGui.QPixmap.fromImage(self.host.image)
                )
                self.host.update_navigator_viewport()
            if hasattr(self.host, "actions") and hasattr(
                self.host.actions, "show_navigator"
            ):
                self.host.actions.show_navigator.setChecked(True)

    def scroll_request(self, delta, orientation, mode):
        scroll_bar = self.host.scroll_bars[orientation]
        units = -delta * (0.1 if mode == 0 else 1)
        step = scroll_bar.singleStep() if mode == 0 else scroll_bar.maximum()
        value = scroll_bar.value() + step * units
        self.host.set_scroll(orientation, value)

    def set_scroll(self, orientation, value):
        self.host.scroll_bars[orientation].setValue(round(value))
        self.host.scroll_values[orientation][self.host.filename] = value
        self.host.update_navigator_viewport()

    def set_zoom(self, value, *, pos=None):
        self.host._zoom_animation.stop()
        self.host.actions.fit_width.setChecked(False)
        self.host.actions.fit_window.setChecked(False)
        self.host.zoom_mode = self.host.MANUAL_ZOOM
        if pos is None:
            self.host._apply_zoom(value)
        else:
            self.host._apply_zoom(
                value,
                self.host.canvas.transform_pos(QtCore.QPointF(pos)),
                QtCore.QPointF(pos) + QtCore.QPointF(self.host.canvas.pos()),
            )

    def add_zoom(self, increment=1.1):
        zoom_value = self.host.canvas.scale * 100 * increment
        if increment > 1:
            zoom_value = math.ceil(zoom_value)
        else:
            zoom_value = math.floor(zoom_value)
        self.host.set_zoom(zoom_value)

    def zoom_request(self, delta, pos):
        if not delta or self.host.image.isNull():
            return
        animation = self.host._zoom_animation
        value = self.host.canvas.scale * 100
        if animation.state() == QtCore.QAbstractAnimation.State.Running:
            value = animation.endValue()
        animation.stop()
        value *= 1.1 ** (max(-12000, min(12000, delta)) / 120.0)
        value = max(
            self.host.zoom_widget.minimum(), min(self.host.zoom_widget.maximum(), value)
        )
        self.host.actions.fit_width.setChecked(False)
        self.host.actions.fit_window.setChecked(False)
        self.host.zoom_mode = self.host.MANUAL_ZOOM
        self.host._zoom_anchor_image = self.host.canvas.transform_pos(
            QtCore.QPointF(pos)
        )
        self.host._zoom_anchor_viewport = QtCore.QPointF(pos) + QtCore.QPointF(
            self.host.canvas.pos()
        )
        with QtCore.QSignalBlocker(animation):
            animation.setStartValue(self.host.canvas.scale * 100)
            animation.setEndValue(float(value))
        animation.start()

    def _animate_zoom(self, value):
        self.host._apply_zoom(
            value, self.host._zoom_anchor_image, self.host._zoom_anchor_viewport
        )

    def _apply_zoom(self, value, image_pos=None, viewport_pos=None):
        if self.host.image.isNull():
            return
        value = max(
            self.host.zoom_widget.minimum(), min(self.host.zoom_widget.maximum(), value)
        )
        if viewport_pos is None:
            viewport_pos = QtCore.QPointF(
                self.host._canvas_scroll_area.viewport().rect().center()
            )
        if image_pos is None:
            image_pos = self.host.canvas.transform_pos(
                viewport_pos - QtCore.QPointF(self.host.canvas.pos())
            )
        with QtCore.QSignalBlocker(self.host.zoom_widget):
            self.host.zoom_widget.setValue(round(value))
        self.host.canvas.scale = value / 100.0
        self.host.canvas.adjustSize()
        canvas_pos = (
            image_pos + self.host.canvas.offset_to_center()
        ) * self.host.canvas.scale
        self.host.canvas.pan_offset += (
            viewport_pos - QtCore.QPointF(self.host.canvas.pos()) - canvas_pos
        )
        self.host.zoom_values[self.host.filename] = (self.host.zoom_mode, value)
        self.host.constrain_canvas_pan()
        self.host.pan_values[self.host.filename] = QtCore.QPointF(self.host.canvas.pan_offset)
        self.host.canvas.update()
        if hasattr(self.host, "navigator_dialog"):
            self.host.navigator_dialog.set_zoom_value(round(value))
        self.host.update_navigator_viewport()

    def constrain_canvas_pan(self):
        if self.host.canvas.wheel_navigation_mode != "traditional":
            return
        offset = self.host.canvas.pan_offset
        self.host.canvas.pan_offset = QtCore.QPointF()
        area = self.host._canvas_scroll_area
        for bar, delta in (
            (area.horizontalScrollBar(), offset.x()),
            (area.verticalScrollBar(), offset.y()),
        ):
            bar.setValue(round(bar.value() - delta))
            self.host.scroll_values[bar.orientation()][self.host.filename] = bar.value()
        self.host.pan_values[self.host.filename] = QtCore.QPointF()
        self.host.canvas.update()
        self.host.update_navigator_viewport()

    def pan_canvas(self, delta):
        self.host._zoom_animation.stop()
        self.host.actions.fit_width.setChecked(False)
        self.host.actions.fit_window.setChecked(False)
        self.host.zoom_mode = self.host.MANUAL_ZOOM
        self.host.zoom_values[self.host.filename] = (
            self.host.zoom_mode,
            self.host.canvas.scale * 100,
        )
        self.host.canvas.pan_offset += delta
        self.host.constrain_canvas_pan()
        self.host.pan_values[self.host.filename] = QtCore.QPointF(self.host.canvas.pan_offset)
        self.host.canvas.update()
        self.host.update_navigator_viewport()

    def set_fit_window(self, value=True):
        if value:
            self.host.actions.fit_width.setChecked(False)
        self.host.zoom_mode = self.host.FIT_WINDOW if value else self.host.MANUAL_ZOOM
        self.host.adjust_scale()

    def set_fit_width(self, value=True):
        if value:
            self.host.actions.fit_window.setChecked(False)
        self.host.zoom_mode = self.host.FIT_WIDTH if value else self.host.MANUAL_ZOOM
        self.host.adjust_scale()

    def set_canvas_params(self, key, value):
        self.host._config[key] = value
        assert hasattr(self.host.canvas, key), f"Canvas has no attribute {key}"
        setattr(self.host.canvas, key, value)
        if key in ("show_labels", "show_linking") and not value:
            self.host.canvas.selected_relation = None
        self.host.canvas.update()

    def paint_canvas(self):
        if self.host.image.isNull():
            return
        self.host._zoom_animation.stop()
        self.host.canvas.adjustSize()
        self.host.canvas.update()
        self.host.update_navigator_viewport()

    def adjust_scale(self, initial=False):
        self.host._zoom_animation.stop()
        self.host.canvas.pan_offset = QtCore.QPointF()
        self.host.pan_values[self.host.filename] = QtCore.QPointF()
        value = self.host.scalers[self.host.FIT_WINDOW if initial else self.host.zoom_mode]()
        value = max(
            self.host.zoom_widget.minimum(),
            min(self.host.zoom_widget.maximum(), int(100 * value)),
        )
        with QtCore.QSignalBlocker(self.host.zoom_widget):
            self.host.zoom_widget.setValue(value)
        self.host.canvas.scale = 0.01 * self.host.zoom_widget.value()
        for scroll_bar in self.host.scroll_bars.values():
            scroll_bar.setValue(0)
        self.host.paint_canvas()
        self.host.zoom_values[self.host.filename] = (self.host.zoom_mode, value)
        if hasattr(self.host, "navigator_dialog"):
            self.host.navigator_dialog.set_zoom_value(value)

    def scale_fit_window(self):
        """Figure out the size of the pixmap to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.host.central_widget().width() - e
        h1 = self.host.central_widget().height() - e
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.host.canvas.pixmap.width() - 0.0
        h2 = self.host.canvas.pixmap.height() - 0.0
        if h1 <= 0 or w2 <= 0 or h2 <= 0:
            return 1.0
        wh_ratio1 = w1 / h1
        wh_ratio2 = w2 / h2
        return w1 / w2 if wh_ratio2 >= wh_ratio1 else h1 / h2

    def scale_fit_width(self):
        # The epsilon does not seem to work too well here.
        w = self.host.central_widget().width() - 2.0
        pw = self.host.canvas.pixmap.width()
        if self.host.canvas.wheel_navigation_mode == "traditional" and pw > 0:
            area = self.host._canvas_scroll_area
            available = area.maximumViewportSize()
            w = available.width() - 2.0
            if self.host.canvas.pixmap.height() * w / pw > available.height():
                w -= area.verticalScrollBar().sizeHint().width()
        return w / pw if pw > 0 else 1.0
