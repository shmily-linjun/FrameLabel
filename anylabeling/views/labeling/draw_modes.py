"""Drawing/editing tool switching and its browse-mode guard.

The toolbar, the Edit menu and the number shortcuts all funnel
into ``toggle_draw_mode``; brush and magic-wand modes plus the edit
mode entry share the same state machine.  The operator gate is asked
for permission before a tool that edits annotations is entered.
"""

from ...services.auto_labeling.types import AutoLabelingMode
from .shape import Shape


class DrawModeController:
    """Tool mode state machine of the labeling canvas."""

    def __init__(self, host):
        self.host = host

    def toggle_drawing_sensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        self.host.actions.edit_mode.setEnabled(not drawing)
        self.host.actions.undo_last_point.setEnabled(drawing)
        self.host.actions.undo.setEnabled(not drawing)
        self.host.actions.delete.setEnabled(not drawing)
        self.host.actions.union_selection.setEnabled(not drawing)
        self.host.update_labeling_instruction()

    def create_digit_mode(self, digit_num):
        if self.host.drawing_digit_shortcuts is None:
            return

        data = self.host.drawing_digit_shortcuts.get(digit_num, None)
        if not data:
            return

        label = data.get("label", "object")
        create_mode = data.get("mode", None)

        if create_mode not in Shape.get_supported_shape():
            return

        self.host.digit_to_label = label
        self.host.toggle_draw_mode(edit=False, create_mode=create_mode)

    def toggle_draw_mode(
        self,
        edit=True,
        create_mode="rectangle",
        disable_auto_labeling=True,
        preserve_brush_mode=False,
    ):
        if not edit and not self.host._ensure_operator_for_edit():
            # Every "create ..." entry point (toolbar, menu, digit shortcut,
            # auto-labeling hand-off) funnels through here, so a cancelled
            # login stops before the canvas switches to a drawing mode.
            return
        if not preserve_brush_mode:
            if getattr(self.host.canvas, "is_brush_mode", False):
                self.host.canvas.cancel_brush_mode()
            elif self.host.actions.edit_brush_mode.isChecked():
                self.host.actions.edit_brush_mode.setChecked(False)
        self.host.canvas.set_magic_wand_mode(False)
        # Disable auto labeling if needed
        if (
            disable_auto_labeling
            and self.host.auto_labeling_widget.auto_labeling_mode
            != AutoLabelingMode.NONE
        ):
            self.host.clear_auto_labeling_marks()
            self.host.auto_labeling_widget.set_auto_labeling_mode(None)

        if not edit:
            self.host.set_text_editing(False)

        self.host.canvas.set_editing(edit)
        self.host.canvas.create_mode = create_mode
        self.host.canvas._brush_drawing = False
        if edit:
            self.host.actions.create_mode.setEnabled(True)
            self.host.actions.create_brush_polygon_mode.setEnabled(True)
            self.host.actions.create_magic_wand_mode.setEnabled(True)
            self.host.actions.create_rectangle_mode.setEnabled(True)
            self.host.actions.create_cuboid_mode.setEnabled(True)
            self.host.actions.create_rotation_mode.setEnabled(True)
            self.host.actions.create_quadrilateral_mode.setEnabled(True)
            self.host.actions.create_circle_mode.setEnabled(True)
            self.host.actions.create_line_mode.setEnabled(True)
            self.host.actions.create_point_mode.setEnabled(True)
            self.host.actions.create_line_strip_mode.setEnabled(True)
            self.host.actions.digit_shortcut_0.setEnabled(True)
            self.host.actions.digit_shortcut_1.setEnabled(True)
            self.host.actions.digit_shortcut_2.setEnabled(True)
            self.host.actions.digit_shortcut_3.setEnabled(True)
            self.host.actions.digit_shortcut_4.setEnabled(True)
            self.host.actions.digit_shortcut_5.setEnabled(True)
            self.host.actions.digit_shortcut_6.setEnabled(True)
            self.host.actions.digit_shortcut_7.setEnabled(True)
            self.host.actions.digit_shortcut_8.setEnabled(True)
            self.host.actions.digit_shortcut_9.setEnabled(True)
        else:
            self.host.hide_attributes_panel()
            self.host.actions.union_selection.setEnabled(False)
            create_actions = {
                "polygon": self.host.actions.create_mode,
                "rectangle": self.host.actions.create_rectangle_mode,
                "cuboid": self.host.actions.create_cuboid_mode,
                "line": self.host.actions.create_line_mode,
                "point": self.host.actions.create_point_mode,
                "circle": self.host.actions.create_circle_mode,
                "linestrip": self.host.actions.create_line_strip_mode,
                "rotation": self.host.actions.create_rotation_mode,
                "quadrilateral": self.host.actions.create_quadrilateral_mode,
            }
            if create_mode not in create_actions:
                raise ValueError(f"Unsupported create_mode: {create_mode}")
            self.host.actions.create_mode.setEnabled(True)
            self.host.actions.create_brush_polygon_mode.setEnabled(True)
            self.host.actions.create_magic_wand_mode.setEnabled(True)
            self.host.actions.create_rectangle_mode.setEnabled(True)
            self.host.actions.create_cuboid_mode.setEnabled(True)
            self.host.actions.create_rotation_mode.setEnabled(True)
            self.host.actions.create_quadrilateral_mode.setEnabled(True)
            self.host.actions.create_circle_mode.setEnabled(True)
            self.host.actions.create_line_mode.setEnabled(True)
            self.host.actions.create_point_mode.setEnabled(True)
            self.host.actions.create_line_strip_mode.setEnabled(True)
            create_actions[create_mode].setEnabled(False)
        self.host.actions.edit_mode.setEnabled(not edit)
        self.host.update_labeling_instruction()
        self.host._apply_operator_gate()

    def toggle_brush_polygon_mode(self):
        """Toggle brush drawing mode for polygons."""
        if (
            self.host.canvas.drawing()
            and self.host.canvas.create_mode == "polygon"
            and self.host.canvas._brush_drawing
        ):
            self.host.toggle_draw_mode(True)
            return
        self.host.toggle_draw_mode(False, create_mode="polygon")
        self.host.canvas._brush_drawing = True
        self.host.actions.create_mode.setEnabled(True)
        self.host.actions.create_brush_polygon_mode.setEnabled(False)

    def toggle_magic_wand_mode(self):
        """Toggle thresholded flood selection for polygon creation."""
        if self.host.canvas.drawing() and self.host.canvas.is_magic_wand_mode:
            self.host.toggle_draw_mode(True)
            return
        self.host.toggle_draw_mode(False, create_mode="polygon")
        self.host.canvas.set_magic_wand_mode(True)
        self.host.actions.create_mode.setEnabled(True)
        self.host.actions.create_magic_wand_mode.setEnabled(False)

    def set_edit_mode(self):
        self.host.clear_auto_labeling_marks()
        self.host.auto_labeling_widget.set_auto_labeling_mode(None)

        self.host.toggle_draw_mode(True)
        self.host.set_text_editing(True)
        self.host.update_labeling_instruction()

    def _enter_edit_mode_from_toolbar(self):
        """Toolbar/menu entry for "Edit Object": ask for a login first."""
        if not self.host._ensure_operator_for_edit():
            return
        self.host.set_edit_mode()

    def toggle_brush_mode(self, checked: bool) -> None:
        """Enable or disable brush editing for a polygon.

        Enabling requires exactly one selected polygon and switches the
        canvas to edit mode before brush editing starts.

        Args:
            checked: ``True`` when the toolbar toggle is switched on.
        """
        if checked:
            if not self.host._ensure_operator_for_edit():
                self.host.actions.edit_brush_mode.setChecked(False)
                return
            selected_shapes = self.host.canvas.selected_shapes
            if (
                len(selected_shapes) != 1
                or selected_shapes[0].shape_type != "polygon"
                or selected_shapes[0].locked
            ):
                self.host.actions.edit_brush_mode.setChecked(False)
                return
            if self.host.canvas.current is not None:
                self.host.canvas.current = None
                self.host.canvas.set_hiding(False)
                self.host.canvas.drawing_polygon.emit(False)
                self.host.canvas.update()
            self.host.toggle_draw_mode(True, preserve_brush_mode=True)
            self.host.set_text_editing(True)
            self.host.canvas.set_brush_mode(True)
            self.host.update_labeling_instruction()
            return

        if getattr(self.host.canvas, "is_brush_mode", False):
            self.host.canvas.set_brush_mode(False)
        self.host.update_labeling_instruction()

    def on_brush_mode_changed(self, enabled: bool) -> None:
        """Synchronize brush action and lock the active shape selection."""
        self.host.actions.edit_brush_mode.setChecked(enabled)
        self.host.label_list.setEnabled(not enabled)
