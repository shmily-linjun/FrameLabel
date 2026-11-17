"""Login, registration and password reset dialogs for operator accounts.

The accounts are a local identity convention: registering and logging in only
establishes who is working, it does not protect the annotation files.  The
dialogs therefore stay deliberately small - no e-mail, no recovery codes, no
roles beyond the implicit first administrator.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from anylabeling.services.identity import (
    OperatorCredentialsError,
    OperatorDisabledError,
    OperatorError,
    OperatorExistsError,
    OperatorNameError,
    OperatorPermissionError,
    OperatorStorageError,
    ReservedOperatorNameError,
)
from anylabeling.services.identity.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordError,
)
from anylabeling.views.labeling.utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_lineedit_style,
    get_normal_button_style,
    get_ok_btn_style,
    get_settings_combo_style,
)

_ERROR_STYLE = "color: #d9534f; font-size: 12px;"
_HINT_STYLE = "color: #8a8a8a; font-size: 12px;"


def _describe_error(dialog, error: Exception) -> str:
    """Map a service exception to a user-facing, translated message."""
    if isinstance(error, OperatorCredentialsError):
        return dialog.tr("Unknown operator or wrong password.")
    if isinstance(error, OperatorDisabledError):
        return dialog.tr("This operator is disabled.")
    if isinstance(error, OperatorExistsError):
        return dialog.tr("This operator name is already registered.")
    if isinstance(error, ReservedOperatorNameError):
        return dialog.tr("This name is reserved.")
    if isinstance(error, PasswordError):
        return dialog.tr("Password must be at least %d characters.") % (
            MIN_PASSWORD_LENGTH,
        )
    if isinstance(error, OperatorNameError):
        return dialog.tr("The operator name is not valid.")
    if isinstance(error, OperatorPermissionError):
        return dialog.tr("This operator cannot manage other accounts.")
    if isinstance(error, OperatorStorageError):
        return dialog.tr("Cannot open the operator database: %s") % str(
            error
        )
    if isinstance(error, OperatorError):
        return str(error)
    return dialog.tr("The operator operation failed: %s") % str(error)


class _FormPage(QWidget):
    """Shared helpers for the pages of :class:`OperatorDialog`."""

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog

    def _label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 13px; font-weight: 500;")
        return label

    def _line_edit(self, password=False):
        edit = QLineEdit()
        edit.setStyleSheet(get_lineedit_style())
        edit.setFixedHeight(34)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    def _button(self, text, style, slot):
        button = QPushButton(text)
        button.setStyleSheet(style)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button


class _LoginPage(_FormPage):
    def __init__(self, dialog, parent=None):
        super().__init__(dialog, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._label(self.tr("Operator name")))
        self.name_combo = QComboBox()
        self.name_combo.setStyleSheet(get_settings_combo_style())
        self.name_combo.setFixedHeight(34)
        layout.addWidget(self.name_combo)

        layout.addWidget(self._label(self.tr("Password")))
        self.password_edit = self._line_edit(password=True)
        self.password_edit.returnPressed.connect(self.dialog.submit_login)
        layout.addWidget(self.password_edit)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(_ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.reset_button = self._button(
            self.tr("Forgot password?"),
            get_normal_button_style(),
            self.dialog.open_password_reset,
        )
        self.register_button = self._button(
            self.tr("Register new operator"),
            get_normal_button_style(),
            self.dialog.show_register_page,
        )
        self.cancel_button = self._button(
            self.tr("Cancel"), get_cancel_btn_style(), self.dialog.reject
        )
        self.login_button = self._button(
            self.tr("Login"), get_ok_btn_style(), self.dialog.submit_login
        )
        self.login_button.setDefault(True)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.register_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.login_button)
        layout.addLayout(buttons)

    def refresh_operators(self, names):
        current = self.name_combo.currentText()
        self.name_combo.clear()
        self.name_combo.addItems(names)
        if current:
            index = self.name_combo.findText(current)
            if index >= 0:
                self.name_combo.setCurrentIndex(index)
        self.password_edit.clear()
        self.error_label.hide()

    def selected_name(self):
        return self.name_combo.currentText().strip()

    def password(self):
        return self.password_edit.text()

    def show_error(self, text):
        self.error_label.setText(text)
        self.error_label.show()

    def set_enabled(self, enabled):
        for widget in (
            self.name_combo,
            self.password_edit,
            self.login_button,
            self.register_button,
            self.reset_button,
        ):
            widget.setEnabled(enabled)


class _RegisterPage(_FormPage):
    def __init__(self, dialog, parent=None):
        super().__init__(dialog, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._label(self.tr("Operator name")))
        self.name_edit = self._line_edit()
        layout.addWidget(self.name_edit)

        layout.addWidget(self._label(self.tr("Password")))
        self.password_edit = self._line_edit(password=True)
        layout.addWidget(self.password_edit)

        layout.addWidget(self._label(self.tr("Confirm password")))
        self.confirm_edit = self._line_edit(password=True)
        self.confirm_edit.returnPressed.connect(self.dialog.submit_register)
        layout.addWidget(self.confirm_edit)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet(_HINT_STYLE)
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        layout.addWidget(self.hint_label)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(_ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.back_button = self._button(
            self.tr("Back to login"),
            get_normal_button_style(),
            self.dialog.show_login_page,
        )
        self.cancel_button = self._button(
            self.tr("Cancel"), get_cancel_btn_style(), self.dialog.reject
        )
        self.register_button = self._button(
            self.tr("Register"),
            get_ok_btn_style(),
            self.dialog.submit_register,
        )
        self.register_button.setDefault(True)
        buttons.addWidget(self.back_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.register_button)
        layout.addLayout(buttons)

    def reset(self, first_account=False):
        self.name_edit.clear()
        self.password_edit.clear()
        self.confirm_edit.clear()
        self.error_label.hide()
        self.hint_label.setVisible(bool(first_account))
        if first_account:
            self.hint_label.setText(
                self.tr(
                    "The first registered account becomes the administrator."
                )
            )

    def values(self):
        return (
            self.name_edit.text(),
            self.password_edit.text(),
            self.confirm_edit.text(),
        )

    def show_error(self, text):
        self.error_label.setText(text)
        self.error_label.show()


class OperatorDialog(QDialog):
    """Login or register an operator and start the annotation session."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(self.tr("Operator Login"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(get_dialog_style())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.title_label = QLabel(self.tr("Login to edit annotations"))
        self.title_label.setStyleSheet(
            "font-size: 15px; font-weight: 600;"
        )
        layout.addWidget(self.title_label)

        self.stack = QStackedWidget()
        self.login_page = _LoginPage(self)
        self.register_page = _RegisterPage(self)
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.register_page)
        layout.addWidget(self.stack)

        self._reload_operators()
        if self._operator_count() == 0:
            self.show_register_page()
        else:
            self.show_login_page()

    # -- data ----------------------------------------------------------------
    def _operator_count(self):
        try:
            return self.service.store.count()
        except OperatorError as error:
            self.login_page.show_error(_describe_error(self, error))
            self.login_page.set_enabled(False)
            return 0

    def _reload_operators(self):
        try:
            operators = self.service.store.list_operators()
        except OperatorError as error:
            self.login_page.show_error(_describe_error(self, error))
            return
        names = [operator.name for operator in operators]
        self.login_page.refresh_operators(names)

    # -- pages ---------------------------------------------------------------
    def show_login_page(self):
        self.stack.setCurrentWidget(self.login_page)
        self.title_label.setText(self.tr("Login to edit annotations"))
        self._reload_operators()
        self.login_page.password_edit.setFocus()

    def show_register_page(self):
        self.register_page.reset(first_account=self._operator_count() == 0)
        self.stack.setCurrentWidget(self.register_page)
        self.title_label.setText(self.tr("Register operator"))
        self.register_page.name_edit.setFocus()

    # -- actions -------------------------------------------------------------
    def submit_login(self):
        name = self.login_page.selected_name()
        password = self.login_page.password()
        if not name:
            self.login_page.show_error(self.tr("Select an operator."))
            return
        try:
            self.service.login(name, password)
        except Exception as error:  # noqa: BLE001 - reported to the user
            self.login_page.show_error(_describe_error(self, error))
            return
        self.accept()

    def submit_register(self):
        name, password, confirm = self.register_page.values()
        if password != confirm:
            self.register_page.show_error(
                self.tr("The passwords do not match.")
            )
            return
        try:
            self.service.register(name, password)
        except Exception as error:  # noqa: BLE001 - reported to the user
            self.register_page.show_error(_describe_error(self, error))
            return
        self.accept()

    def open_password_reset(self):
        dialog = PasswordResetDialog(self.service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload_operators()
            self.login_page.show_error("")
            self.login_page.error_label.hide()


class PasswordResetDialog(QDialog):
    """Reset an operator password after authenticating an administrator."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(self.tr("Reset password"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(get_dialog_style())

        self._operators = []
        try:
            self._operators = service.store.list_operators()
        except OperatorError:
            self._operators = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(self._make_label(self.tr("Administrator")))
        self.admin_combo = self._make_combo()
        layout.addWidget(self.admin_combo)

        layout.addWidget(self._make_label(self.tr("Administrator password")))
        self.admin_password = self._make_password_edit()
        layout.addWidget(self.admin_password)

        layout.addWidget(self._make_label(self.tr("Target operator")))
        self.target_combo = self._make_combo()
        layout.addWidget(self.target_combo)

        layout.addWidget(self._make_label(self.tr("New password")))
        self.new_password = self._make_password_edit()
        layout.addWidget(self.new_password)

        layout.addWidget(self._make_label(self.tr("Confirm password")))
        self.confirm_password = self._make_password_edit()
        self.confirm_password.returnPressed.connect(self.submit)
        layout.addWidget(self.confirm_password)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(_ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        cancel_button = QPushButton(self.tr("Cancel"))
        cancel_button.setStyleSheet(get_cancel_btn_style())
        cancel_button.clicked.connect(self.reject)
        ok_button = QPushButton(self.tr("Reset password"))
        ok_button.setStyleSheet(get_ok_btn_style())
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.submit)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)
        layout.addLayout(buttons)

        self._fill_combos()

    def _make_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 13px; font-weight: 500;")
        return label

    def _make_combo(self):
        combo = QComboBox()
        combo.setStyleSheet(get_settings_combo_style())
        combo.setFixedHeight(34)
        return combo

    def _make_password_edit(self):
        edit = QLineEdit()
        edit.setStyleSheet(get_lineedit_style())
        edit.setFixedHeight(34)
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    def _fill_combos(self):
        names = [operator.name for operator in self._operators]
        self.admin_combo.addItems(names)
        self.target_combo.addItems(names)
        admins = [
            operator.name
            for operator in self._operators
            if operator.is_admin
        ]
        if len(admins) == 1:
            index = self.admin_combo.findText(admins[0])
            if index >= 0:
                self.admin_combo.setCurrentIndex(index)

    def submit(self):
        if self.new_password.text() != self.confirm_password.text():
            self._show_error(self.tr("The passwords do not match."))
            return
        try:
            self.service.store.change_password(
                self.target_combo.currentText(),
                self.new_password.text(),
                admin_name=self.admin_combo.currentText(),
                admin_password=self.admin_password.text(),
            )
        except Exception as error:  # noqa: BLE001 - reported to the user
            self._show_error(_describe_error(self, error))
            return
        self.accept()

    def _show_error(self, text):
        self.error_label.setText(text)
        self.error_label.show()
