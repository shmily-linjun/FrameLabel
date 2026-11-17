"""Compact operator session bar shown above the canvas.

The bar is the always-visible answer to "who is logged in and can I edit?".
Disabled tools alone are easy to mistake for a defect, so the mode and the
login entry point must always be visible.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from anylabeling.services.identity.attribution import (
    AUTHOR_NONE,
    format_display_time,
)
from anylabeling.views.labeling.utils.style import (
    get_normal_button_style,
    get_ok_btn_style,
)

_STATE_STYLE = "font-size: 12px; font-weight: 600;"
_ATTRIBUTION_STYLE = "font-size: 12px; color: #8a8a8a;"


class OperatorBar(QWidget):
    """Shows the current operator and offers login/logout."""

    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._attribution_text = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(10)

        self.state_label = QLabel("")
        self.state_label.setStyleSheet(_STATE_STYLE)
        layout.addWidget(self.state_label)

        self.attribution_label = QLabel("")
        self.attribution_label.setStyleSheet(_ATTRIBUTION_STYLE)
        layout.addWidget(self.attribution_label)

        layout.addStretch()

        self.login_button = QPushButton(self.tr("Login"))
        self.login_button.setStyleSheet(get_ok_btn_style())
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self.login_requested.emit)
        layout.addWidget(self.login_button)

        self.logout_button = QPushButton(self.tr("Logout"))
        self.logout_button.setStyleSheet(get_normal_button_style())
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.clicked.connect(self.logout_requested.emit)
        layout.addWidget(self.logout_button)

        self._unsubscribe = self.service.session.subscribe(
            lambda _session: self.refresh()
        )
        self.refresh()

    def refresh(self):
        operator = self.service.session.operator
        if operator is None:
            self.state_label.setText(
                self.tr("Browse mode - editing annotations requires login")
            )
            self.login_button.show()
            self.logout_button.hide()
        else:
            self.state_label.setText(
                self.tr("Annotation mode: %s") % operator.name
            )
            self.login_button.hide()
            self.logout_button.show()
        self.attribution_label.setText(self._attribution_text)

    def set_attribution(self, author, modified_at):
        """Show the attribution of the current image (display only)."""
        if not author or author == AUTHOR_NONE:
            text = self.tr("Author: not recorded")
        else:
            when = format_display_time(modified_at)
            detail = f"{author} · {when}" if when else author
            text = self.tr("Last modified: %s") % detail
        self._attribution_text = text
        self.attribution_label.setText(text)

    def closeEvent(self, event):
        try:
            self._unsubscribe()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass
        super().closeEvent(event)
