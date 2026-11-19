"""Operator session chrome: a menu-bar chip and a status-bar attribution.

Both widgets are deliberately tiny and framework-native.  The login entry
lives in the menu bar corner and the "last modified by" text in the status
bar, so neither costs any canvas height - the canvas is the main working
area of the application and must not be squeezed by account chrome.

The chips only display state; :class:`anylabeling.views.labeling.label_widget`
owns the session, the login dialog and the attribution formatting inputs.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from anylabeling.services.identity.attribution import (
    AUTHOR_NONE,
    format_display_time,
)
from anylabeling.views.labeling.utils.style import (
    get_compact_button_style,
)
from anylabeling.views.labeling.utils.theme import get_theme

_ATTRIBUTION_STYLE = "font-size: 12px; color: #8a8a8a; padding-right: 8px;"


def _state_style(color, bold=False):
    weight = "font-weight: 600;" if bold else ""
    return f"font-size: 12px; color: {color}; padding: 0px 4px; {weight}"


class OperatorBar(QWidget):
    """Compact operator chip: mode text plus login/logout button."""

    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("OperatorBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        self.state_label = QLabel("")
        layout.addWidget(self.state_label)

        self.login_button = QPushButton(self.tr("Login"))
        self.login_button.setStyleSheet(get_compact_button_style(primary=True))
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self.login_requested.emit)
        layout.addWidget(self.login_button)

        self.logout_button = QPushButton(self.tr("Logout"))
        self.logout_button.setStyleSheet(get_compact_button_style())
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.clicked.connect(self.logout_requested.emit)
        layout.addWidget(self.logout_button)

        self.setToolTip(
            self.tr("Browse mode - editing annotations requires login")
        )
        unsubscribe = self.service.session.subscribe(
            lambda _session: self.refresh()
        )
        self._unsubscribe = unsubscribe
        # The chip is reparented into the window chrome; closeEvent is not
        # guaranteed then, so also drop the listener when Qt destroys it.
        self.destroyed.connect(lambda *_args: unsubscribe())
        self.refresh()

    def refresh(self):
        theme = get_theme()
        operator = self.service.session.operator
        if operator is None:
            # Browse mode must be visible at a glance: the previous fixed gray
            # was unreadable in the dark theme and users mistook the disabled
            # tools for a bug.  Reuse the existing translated wording so no
            # translation rebuild is needed for this fix.
            self.state_label.setText(self.tr("Not logged in"))
            self.state_label.setStyleSheet(
                _state_style(theme["warning_text"], bold=True)
            )
            self.login_button.show()
            self.logout_button.hide()
            self.setToolTip(
                self.tr("Browse mode - editing annotations requires login")
            )
        else:
            self.state_label.setText(
                self.tr("Annotation mode: %s") % operator.name
            )
            self.state_label.setStyleSheet(
                _state_style(theme["text_secondary"])
            )
            self.login_button.hide()
            self.logout_button.show()
            self.setToolTip(self.tr("Annotation mode: %s") % operator.name)

    def closeEvent(self, event):
        try:
            self._unsubscribe()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass
        super().closeEvent(event)


class AttributionLabel(QLabel):
    """Status-bar text showing who last modified the current image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            _ATTRIBUTION_STYLE.replace(
                "#8a8a8a", get_theme()["text_secondary"]
            )
        )
        self.clear_attribution()

    def clear_attribution(self):
        self.setText(self.tr("Author: not recorded"))

    def set_attribution(self, author, modified_at):
        if not author or author == AUTHOR_NONE:
            self.clear_attribution()
            return
        when = format_display_time(modified_at)
        detail = f"{author} · {when}" if when else author
        self.setText(self.tr("Last modified: %s") % detail)
