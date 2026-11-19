"""Browse-mode gate and attribution stamping for the labeling window.

Without a logged-in operator the application runs in *browse mode*: the
annotation is read-only, the mode tools stay clickable (so a click can explain
that login is required) and content-changing commands are disabled.  The same
object decides when a save must stamp ``author``/``modified_at`` and when the
content really changed.

This class owns that policy and the session-dependent state (browse flag,
last written signature, suppression for "carry shapes over" style loads).  It
mutates widgets owned by the host but has no UI of its own, so it can be tested
with a stand-in host.
"""

import os.path as osp

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from ....services.auto_labeling.types import AutoLabelingMode
from ....services.identity import (
    content_signature,
    read_attribution,
    stamp_attribution,
)
from ..widgets.operator_dialog import OperatorDialog

#: Actions that switch the drawing/editing tool.  They stay clickable while
#: nobody is logged in so a click can explain itself with a login prompt
#: (the entry itself is guarded in ``toggle_draw_mode``/``toggle_brush_mode``);
#: disabling them silently made browse mode look like a broken toolbar.
OPERATOR_MODE_ACTIONS = (
    "create_mode",
    "create_brush_polygon_mode",
    "create_magic_wand_mode",
    "create_rectangle_mode",
    "create_cuboid_mode",
    "create_rotation_mode",
    "create_quadrilateral_mode",
    "create_circle_mode",
    "create_line_mode",
    "create_point_mode",
    "create_line_strip_mode",
    "edit_mode",
    "edit_brush_mode",
)

#: Actions that change annotation content or image tags and therefore need a
#: logged-in operator.  Register new editing actions here, otherwise the
#: write-time guard would be the only thing catching them.
OPERATOR_REQUIRED_ACTIONS = (
    "edit",
    "delete",
    "duplicate",
    "paste",
    "undo",
    "undo_last_point",
    "remove_point",
    "union_selection",
    "create_relation",
    "manage_relations",
    "group_selected_shapes",
    "ungroup_selected_shapes",
    "label_manager",
    "gid_manager",
    "shape_manager",
    "run_all_images",
)

_AUTOLABEL_MARK_LABELS = (
    AutoLabelingMode.OBJECT,
    AutoLabelingMode.ADD,
    AutoLabelingMode.REMOVE,
)


class OperatorGate:
    """Apply browse mode and decide when a save stamps the author.

    Host contract (implemented by
    :class:`anylabeling.views.labeling.label_widget.LabelingWidget`):

    * ``operator_service`` -- :class:`OperatorService` with a live session;
    * ``actions`` / ``canvas`` / ``image_tags_widget`` -- widgets to gate;
    * ``filename`` / ``image_path`` / ``dirty`` / ``output_dir`` -- state;
    * ``other_data`` -- annotation payload the author is stamped into;
    * ``label_list`` / ``flag_widget`` -- content used for the signature;
    * ``attribution_label`` -- status bar attribution display (optional);
    * ``tr()`` / ``status()`` / ``save_labels()`` / ``toggle_draw_mode()``;
    * ``_refresh_browse_mode_badge()`` -- repaint the on-canvas browse badge.
    """

    def __init__(self, host, operator_service):
        self.host = host
        self.service = operator_service
        #: Content signature of the file last loaded/saved; ``None`` until the
        #: first save of the current image.
        self.baseline = None
        #: Set while shapes are carried over from the previous image, which
        #: must not be attributed to anyone.
        self.suppress = False
        self._applying = False

    # -- session state ---------------------------------------------------
    def logged_in(self):
        return self.service.session.is_logged_in

    def on_session_changed(self, _session=None):
        self.apply()
        self.refresh_display()

    # -- browse mode -----------------------------------------------------
    def apply(self):
        """Apply browse mode (no operator) to the tools, canvas and chip.

        Browse mode is a real read-only state: the command actions are
        disabled, the canvas ignores editing gestures, and the mode tools stay
        clickable so a click can ask for the login it needs.
        """
        if self._applying:
            return
        self._applying = True
        host = self.host
        try:
            allowed = self.logged_in()
            for name in OPERATOR_MODE_ACTIONS:
                action = getattr(host.actions, name, None)
                if action is not None:
                    action.setEnabled(True)
            for name in OPERATOR_REQUIRED_ACTIONS:
                action = getattr(host.actions, name, None)
                if action is not None:
                    action.setEnabled(bool(allowed and host.filename))
            canvas = getattr(host, "canvas", None)
            if canvas is not None:
                canvas.set_read_only(not allowed)
            tags_widget = getattr(host, "image_tags_widget", None)
            if tags_widget is not None:
                tags_widget.set_interactions_enabled(
                    bool(allowed and host.image_path)
                )
            host._refresh_browse_mode_badge()
        finally:
            self._applying = False

    def open_login(self):
        """Ask for an operator and log in; returns True when logged in."""
        host = self.host
        if self.service.session.is_logged_in:
            return True
        dialog = OperatorDialog(self.service, host)
        return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted

    def logout(self):
        host = self.host
        if not self.service.session.is_logged_in:
            return
        if host.dirty and host.image_path:
            label_file = osp.splitext(host.image_path)[0] + ".json"
            if host.output_dir:
                label_file = osp.join(
                    host.output_dir, osp.basename(label_file)
                )
            host.save_labels(label_file)
        host.toggle_draw_mode(True)
        self.service.logout()

    def ensure_operator(self):
        """Require an operator before content is written; prompts if needed."""
        if self.logged_in():
            return True
        return self.open_login()

    def ensure_for_edit(self):
        """Ask for a login before entering a tool that edits annotations.

        Returns ``True`` when the action may continue.  A cancelled login
        leaves everything untouched and says why in the status bar, so the
        click is never silently swallowed.
        """
        host = self.host
        if self.logged_in():
            return True
        if self.open_login():
            return True
        self.apply()
        host.status(
            host.tr("Browse mode - editing annotations requires login")
        )
        return False

    # -- attribution -----------------------------------------------------
    def prepare_attribution(self, shapes, flags):
        """Stamp the author when the content really changed.

        Returns ``(signature, allowed)``; ``allowed`` is ``False`` when the
        content changed but no operator is available, in which case the caller
        must not write the file.
        """
        host = self.host
        signature = content_signature(shapes, flags, host.other_data)
        if self.suppress or signature == self.baseline:
            return signature, True
        operator_name = self.service.session.operator_name
        if not operator_name:
            if not self.ensure_operator():
                return signature, False
            operator_name = self.service.session.operator_name
            if not operator_name:
                return signature, False
        stamp_attribution(host.other_data, operator_name)
        return signature, True

    def content_signature_now(self):
        host = self.host
        shapes = [
            item.shape().to_dict()
            for item in host.label_list
            if item.shape().label not in _AUTOLABEL_MARK_LABELS
        ]
        flags = {}
        for i in range(host.flag_widget.count()):
            item = host.flag_widget.item(i)
            flags[item.text()] = item.checkState() == Qt.CheckState.Checked
        return content_signature(shapes, flags, host.other_data)

    def refresh_display(self):
        host = self.host
        label = getattr(host, "attribution_label", None)
        if label is None:
            return
        if not host.image_path:
            label.clear_attribution()
            return
        author, modified_at = read_attribution(host.other_data)
        label.set_attribution(author, modified_at)
