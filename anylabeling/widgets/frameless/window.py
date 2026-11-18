"""Frameless main window with an embedded title bar and real menu bar.

The window is a ``QMainWindow`` subclass so toolbars, dock widgets and the
status bar keep working unchanged.  In frameless mode the native caption is
replaced by :class:`TitleBar`; in native mode the same menu bar is installed
with ``setMenuBar`` instead, so the host never sees two sets of window
buttons.

Platform support: Windows is the primary target (native hit testing keeps
resize, snap and maximize-on-work-area).  Other platforms fall back to
``QWindow.startSystemResize`` for edge resizing and may lose some behaviours;
see the design document for the accepted limitations.
"""

from __future__ import annotations

import ctypes
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

from .hit_test import HTCLIENT, edges_at, hit_test_code, qt_edges
from .menu_bar import FrameMenuBar
from .theme import FramelessTheme
from .title_bar import TitleBar, TitleButton
from . import window_state

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_WM_GETMINMAXINFO = 0x0024

_GWL_STYLE = -16
_WS_THICKFRAME = 0x00040000
# NOSIZE | NOMOVE | NOZORDER | NOACTIVATE | FRAMECHANGED
_SWP_FRAME_FLAGS = 0x0037


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MinMaxInfo(ctypes.Structure):
    _fields_ = [
        ("ptReserved", _Point),
        ("ptMaxSize", _Point),
        ("ptMaxPosition", _Point),
        ("ptMinTrackSize", _Point),
        ("ptMaxTrackSize", _Point),
    ]


class FramelessWindow(QtWidgets.QMainWindow):
    """QMainWindow with optional custom title bar and embedded menu bar."""

    fullscreen_changed = QtCore.pyqtSignal(bool)
    menu_visibility_changed = QtCore.pyqtSignal(dict)

    def __init__(self, frameless: bool = True, parent=None):
        super().__init__(parent)
        self._frameless = bool(frameless)
        self._theme = FramelessTheme()
        self._menu_bar = FrameMenuBar(self, in_window=self._frameless)
        self._title_bar = None
        self._fullscreen_restore_mode = "normal"
        self._display_title = None

        self._fullscreen_action = QtGui.QAction(
            self.tr("Toggle Full Screen"), self
        )
        self._fullscreen_action.setShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key.Key_F11)
        )
        self._fullscreen_action.setCheckable(True)
        self._fullscreen_action.triggered.connect(
            lambda _checked=False: self.toggle_fullscreen()
        )
        self.addAction(self._fullscreen_action)

        if self._frameless:
            self.setWindowFlag(
                QtCore.Qt.WindowType.FramelessWindowHint, True
            )
            self._title_bar = TitleBar(self, self._theme, self)
            self._title_bar.attach_menu_bar(self._menu_bar)
            self.setMenuWidget(self._title_bar)
            if sys.platform != "win32":
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    app.installEventFilter(self)
        else:
            self.setMenuBar(self._menu_bar)

        self._menu_bar.menu_visibility_changed.connect(
            self.menu_visibility_changed.emit
        )
        self.apply_theme(self._theme)

    # -- public accessors ----------------------------------------------------
    @property
    def frameless(self) -> bool:
        return self._frameless

    @property
    def title_bar(self):
        return self._title_bar

    @property
    def menu_bar(self) -> FrameMenuBar:
        return self._menu_bar

    @property
    def fullscreen_action(self) -> QtGui.QAction:
        return self._fullscreen_action

    def menuBar(self):  # noqa: N802 - Qt naming
        """Return the embedded menu bar in both modes."""
        bar = getattr(self, "_menu_bar", None)
        if bar is None:
            return super().menuBar()
        return bar

    # -- content -------------------------------------------------------------
    def set_content_widget(self, widget) -> None:
        self.setCentralWidget(widget)

    def set_app_title(self, text: str) -> None:
        self.setWindowTitle(text)

    def set_display_title(self, text: str) -> None:
        """Set the custom title bar text (separate from the OS title)."""
        self._display_title = text
        if self._title_bar is not None:
            self._title_bar.set_title(text)

    def setWindowTitle(self, title: str) -> None:  # noqa: N802 - Qt naming
        super().setWindowTitle(title)
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            display = getattr(self, "_display_title", None)
            title_bar.set_title(display if display is not None else title)

    def set_app_icon(self, icon) -> None:
        if isinstance(icon, str):
            icon = QtGui.QIcon(icon)
        self.setWindowIcon(icon)

    def setWindowIcon(self, icon) -> None:  # noqa: N802 - Qt naming
        super().setWindowIcon(icon)
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.set_icon(icon)

    # -- theme ---------------------------------------------------------------
    def apply_theme(self, theme) -> None:
        if isinstance(theme, FramelessTheme):
            resolved = theme
        else:
            resolved = FramelessTheme.from_mapping(theme)
        self._theme = resolved
        self.setStyleSheet(resolved.stylesheet())
        if self._title_bar is not None:
            self._title_bar.set_theme(resolved)

    # -- menus ---------------------------------------------------------------
    def add_menu(self, title: str):
        return self._menu_bar.add_menu(title)

    def set_menu_visible(self, title: str, visible: bool) -> None:
        self._menu_bar.set_menu_visible(title, visible)

    def restore_menu_visibility(self, state) -> None:
        self._menu_bar.restore_visibility(state)

    def menu_visibility_state(self) -> dict:
        return self._menu_bar.visibility_state()

    # -- title buttons -------------------------------------------------------
    def add_title_button(self, spec: TitleButton):
        if self._title_bar is None:
            raise RuntimeError("Title buttons require frameless mode")
        return self._title_bar.add_button(spec)

    def add_title_widget(self, widget, key: str = ""):
        if self._title_bar is None:
            raise RuntimeError("Title widgets require frameless mode")
        return self._title_bar.add_widget(widget, key)

    def remove_title_button(self, key: str) -> None:
        if self._title_bar is not None:
            self._title_bar.remove_button(key)

    def title_button(self, key: str):
        if self._title_bar is None:
            return None
        return self._title_bar.button(key)

    # -- window controls -----------------------------------------------------
    def toggle_maximize(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()
            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def restore_window(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()
            return
        self.showNormal()

    def minimize(self) -> None:
        self.showMinimized()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            restored = window_state.next_mode_after_restore(
                self._fullscreen_restore_mode
            )
            self.showNormal()
            if restored == window_state.MODE_MAXIMIZED:
                self.showMaximized()
            self._fullscreen_action.setChecked(False)
            self.fullscreen_changed.emit(False)
            return
        self._fullscreen_restore_mode = (
            "maximized" if self.isMaximized() else "normal"
        )
        self.showFullScreen()
        self._fullscreen_action.setChecked(True)
        self.fullscreen_changed.emit(True)

    def showEvent(self, event):  # noqa: N802 - Qt naming
        super().showEvent(event)
        if self._frameless and sys.platform == "win32":
            self._ensure_native_resize_frame()

    def _ensure_native_resize_frame(self) -> None:
        """Give the frameless window a sizing frame through native styles.

        ``WM_NCHITTEST`` alone is not enough: Windows only starts a sizing
        operation for windows that carry ``WS_THICKFRAME``.  The style is
        added after Qt created the window and the resulting non-client area
        is removed again in ``nativeEvent`` (``WM_NCCALCSIZE``).
        """
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            get_style = user32.GetWindowLongPtrW
            get_style.restype = ctypes.c_ssize_t
            get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_style = user32.SetWindowLongPtrW
            set_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_ssize_t,
            ]
            style = get_style(hwnd, _GWL_STYLE)
            if style & _WS_THICKFRAME:
                return
            set_style(hwnd, _GWL_STYLE, style | _WS_THICKFRAME)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0, _SWP_FRAME_FLAGS
            )
        except (AttributeError, OSError, TypeError):
            return

    # -- events --------------------------------------------------------------
    def event(self, event):  # noqa: N802 - Qt naming
        event_type = event.type()
        if event_type == QtCore.QEvent.Type.WindowActivate:
            if self._title_bar is not None:
                self._title_bar.set_active(True)
        elif event_type == QtCore.QEvent.Type.WindowDeactivate:
            if self._title_bar is not None:
                self._title_bar.set_active(False)
        elif event_type == QtCore.QEvent.Type.WindowStateChange:
            if self._title_bar is not None:
                self._title_bar.set_maximized(self.isMaximized())
            self._fullscreen_action.setChecked(self.isFullScreen())
        return super().event(event)

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        if self._frameless and sys.platform != "win32":
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        super().closeEvent(event)

    # -- non-Windows resize fallback ----------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if (
            event.type() != QtCore.QEvent.Type.MouseButtonPress
            or not isinstance(obj, QtWidgets.QWidget)
            or obj.window() is not self
        ):
            return super().eventFilter(obj, event)
        try:
            global_pos = obj.mapToGlobal(event.position().toPoint())
        except AttributeError:
            return super().eventFilter(obj, event)
        local = self.mapFromGlobal(global_pos)
        margin = self._theme.resize_margin
        edges = edges_at(
            local.x(), local.y(), self.width(), self.height(), margin
        )
        if not edges:
            return super().eventFilter(obj, event)
        handle = self.windowHandle()
        if handle is not None and hasattr(handle, "startSystemResize"):
            handle.startSystemResize(qt_edges(edges))
            return True
        return super().eventFilter(obj, event)

    # -- Windows native behaviour -------------------------------------------
    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt naming
        # Never call ``super().nativeEvent()`` here: on PyQt6/Windows that
        # re-enters this override and crashes the process at show time.
        # Returning ``(False, 0)`` is the documented "not handled" result.
        if not self._frameless or sys.platform != "win32":
            return False, 0
        try:
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
        except (ImportError, ValueError, TypeError):
            return False, 0
        if msg.message == _WM_NCCALCSIZE and msg.wParam:
            # Returning 0 with wParam=TRUE makes the client area cover the
            # whole window, hiding the sizing frame we added above.
            return True, 0
        if msg.message == _WM_NCHITTEST:
            if self.isMaximized() or self.isFullScreen():
                return True, HTCLIENT
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            ratio = self.devicePixelRatioF() or 1.0
            point = QtCore.QPoint(round(x / ratio), round(y / ratio))
            local = self.mapFromGlobal(point)
            margin = self._theme.resize_margin
            code = hit_test_code(
                local.x(), local.y(), self.width(), self.height(), margin
            )
            return True, code
        if msg.message == _WM_GETMINMAXINFO:
            self._apply_minmax_info(msg.lParam)
            return True, 0
        return False, 0

    def _apply_minmax_info(self, lparam: int) -> None:
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        ratio = screen.devicePixelRatio() or 1.0
        work = screen.availableGeometry()
        full = screen.geometry()
        info = _MinMaxInfo.from_address(lparam)
        info.ptMaxPosition.x = int(round(work.x() * ratio))
        info.ptMaxPosition.y = int(round(work.y() * ratio))
        info.ptMaxSize.x = int(round(work.width() * ratio))
        info.ptMaxSize.y = int(round(work.height() * ratio))
        info.ptMaxTrackSize.x = int(round(full.width() * ratio))
        info.ptMaxTrackSize.y = int(round(full.height() * ratio))
