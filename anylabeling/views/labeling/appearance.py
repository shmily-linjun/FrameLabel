"""Theme, language, shortcuts and on-canvas instruction text.

These commands change how the labeling window looks and what it explains; they
do not touch annotation content.  Keeping them together keeps the theme and
translation refresh rules in one place instead of interleaving them with the
editing flow.

The host (``LabelingWidget``) owns the widgets and the settings backend; this
class is stateless and only reads/mutates the host.
"""

import html
import zlib

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import QLabel, QMessageBox

from ...config import save_config
from .settings import SettingsDialog
from .settings.schema import SETTINGS_SHORTCUT_SECTIONS, fields_for_page
from .utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
)
from .widgets.popup import Popup

# pylupdate6 only records `tr()` calls inside class bodies.  These
# modules also translate text through `host.tr`/`self.tr` in free
# functions and helpers, where the receiver is the LabelingWidget; the
# constant tells `scripts/translation_scan.py` which context to use
# (see docs/dev/CODE_STRUCTURE_REPORT.md).
TR_CONTEXT = "LabelingWidget"


class AppearanceController:
    """Theme/language refresh and instruction hints."""

    def __init__(self, host):
        self.host = host

    def show_shortcuts(self):
        from .pointcloud.controls import ShortcutsDialog

        shortcuts = self.host._config["shortcuts"]
        groups = []
        for section in SETTINGS_SHORTCUT_SECTIONS:
            entries = []
            for field in fields_for_page("Shortcuts", section):
                value = shortcuts.get(field.key.removeprefix("shortcuts."))
                values = value if isinstance(value, (list, tuple)) else [value]
                keys = [
                    QtGui.QKeySequence(key).toString(
                        QtGui.QKeySequence.SequenceFormat.NativeText
                    )
                    for key in values
                    if key
                ]
                if keys:
                    entries.append(
                        (
                            QtCore.QCoreApplication.translate(
                                "SettingsDialog", field.label
                            ),
                            keys,
                        )
                    )
            if section == "Shape":
                entries.extend(
                    (
                        getattr(
                            self.host.actions, f"digit_shortcut_{digit}"
                        ).text(),
                        [str(digit)],
                    )
                    for digit in range(10)
                )
            groups.append(
                (
                    QtCore.QCoreApplication.translate(
                        "SettingsDialog", section
                    ),
                    entries,
                )
            )
        ShortcutsDialog(groups, self.host).exec()

    def set_language(self, language):
        if self.host._config["language"] == language:
            return
        self.host._config["language"] = language

        # Show dialog to restart application
        msg_box = QMessageBox()
        msg_box.setText(
            self.host.tr("Please restart the application to apply changes.")
        )
        msg_box.exec()
        self.host.parent.parent.close()

    def _on_theme_changed(self, mode: str) -> None:
        """Handle Theme menu selection (System / Light / Dark)."""
        prev_mode = self.host._config.get("theme", "auto")
        if prev_mode == mode:
            return

        dialog = QtWidgets.QDialog(self.host)
        dialog.setWindowTitle(self.host.tr("Theme"))
        dialog.setFixedWidth(360)
        dialog.setWindowFlags(
            dialog.windowFlags()
            & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        dialog.setStyleSheet(get_dialog_style())

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        label = QLabel(
            self.host.tr(
                "The new theme will take effect after restarting the application. Apply this setting now?"
            )
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(8)
        cancel_btn = QtWidgets.QPushButton(self.host.tr("Cancel"))
        cancel_btn.setFixedWidth(100)
        cancel_btn.setStyleSheet(get_cancel_btn_style())
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn = QtWidgets.QPushButton(self.host.tr("OK"))
        ok_btn.setFixedWidth(100)
        ok_btn.setStyleSheet(get_ok_btn_style())
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.host._config["theme"] = mode
            save_config(self.host._config)
            popup = Popup(
                text=self.host.tr(
                    "Please restart the application to apply changes."
                ),
                parent=self.host,
            )
            popup.show_popup(self.host, position="center")
        else:
            # Revert the checkmark to the previously active mode
            prev_act = self.host._theme_actions.get(prev_mode)
            if prev_act:
                prev_act.setChecked(True)

    def get_labeling_instruction(self):
        text_mode = self.host.tr("Mode:")
        text_shortcuts = self.host.tr("Shortcuts:")
        text_settings = self.host.tr("Settings")
        text_previous = self.host.tr("Previous")
        text_next = self.host.tr("Next")
        text_rectangle = self.host.tr("Rectangle")
        text_polygon = self.host.tr("Polygon")
        text_rotation = self.host.tr("Rotation")
        text_quadrilateral = self.host.tr("Quadrilateral")
        shortcuts = self.host._config.get("shortcuts", {})
        return (
            f"<b>{text_mode}</b> {self.host.canvas.get_mode()} | "
            f"<b>{text_shortcuts}</b>"
            f" {text_previous}({self.host._format_instruction_shortcut(shortcuts.get('open_prev'))}),"
            f" {text_next}({self.host._format_instruction_shortcut(shortcuts.get('open_next'))}),"
            f" {text_rectangle}({self.host._format_instruction_shortcut(shortcuts.get('create_rectangle'))}),"
            f" {text_polygon}({self.host._format_instruction_shortcut(shortcuts.get('create_polygon'))}),"
            f" {text_rotation}({self.host._format_instruction_shortcut(shortcuts.get('create_rotation'))}),"
            f" {text_quadrilateral}({self.host._format_instruction_shortcut(shortcuts.get('create_quadrilateral'))}),"
            f" {text_settings}({self.host._format_instruction_shortcut(shortcuts.get('open_settings'))})"
        )

    def _should_show_space_pan_tip(self):
        if not self.host.canvas.drawing() or self.host.canvas.current is None:
            return False
        return any(
            scroll_bar.maximum() > 0
            for scroll_bar in self.host.scroll_bars.values()
        )

    def _space_pan_tip_message(self):
        return self.host.tr(
            "Tip: Hold Alt and drag with the left mouse button, or drag with the middle mouse button, to pan the canvas while drawing."
        )

    def update_space_pan_tip(self):
        message = self.host._space_pan_tip_message()
        status_bar = self.host.statusBar()
        if self.host._should_show_space_pan_tip():
            status_bar.showMessage(message)
        elif status_bar.currentMessage() == message:
            status_bar.clearMessage()

    def update_labeling_instruction(self):
        if not hasattr(self.host, "label_instruction"):
            return
        self.host.label_instruction.setText(self.host.get_labeling_instruction())
        self.host.update_space_pan_tip()

    def _format_instruction_shortcut(self, value):
        text = self.host._settings_runtime_applier.shortcut_value_to_text(
            value
        ).strip()
        if not text:
            return "<b>-</b>"
        sequences = [
            chunk.strip() for chunk in text.split(",") if chunk.strip()
        ]
        if not sequences:
            return "<b>-</b>"
        formatted = []
        for sequence in sequences:
            keys = [
                part.strip() for part in sequence.split("+") if part.strip()
            ]
            if not keys:
                continue
            formatted.append(
                "+".join(f"<b>{html.escape(key)}</b>" for key in keys)
            )
        if not formatted:
            return "<b>-</b>"
        return ", ".join(formatted)

    def show_image_tags_editor(self):
        """Open the image-attributes tab and focus the image tags editor."""
        host = self.host
        if hasattr(host, "show_right_tab"):
            host.show_right_tab("flags")
        widget = getattr(host, "image_tags_widget", None)
        if widget is not None:
            widget.setFocus()

    def _get_rgb_by_image_tag(self, label):
        for shape in self.host.canvas.shapes:
            if shape.label == label:
                return shape.line_color.getRgb()[:3]
        label_colors = self.host._config.get("label_colors") or {}
        if label in label_colors:
            return tuple(label_colors[label])
        label_id = zlib.crc32(label.encode("utf-8"))
        hue = label_id % 360
        saturation = 110 + ((label_id >> 9) % 66)
        value = 225 + ((label_id >> 16) % 26)
        return QtGui.QColor.fromHsv(hue, saturation, value).getRgb()[:3]

    def open_settings_dialog(self, _checked=False, field_key=None):
        if self.host._settings_controller is None:
            return
        if self.host._settings_dialog is None:
            self.host._settings_dialog = SettingsDialog(
                self.host, self.host._settings_controller
            )
        if field_key is not None:
            self.host._settings_dialog.show_field(field_key)
        self.host._settings_dialog.show()
        self.host._settings_dialog.raise_()
        self.host._settings_dialog.activateWindow()
