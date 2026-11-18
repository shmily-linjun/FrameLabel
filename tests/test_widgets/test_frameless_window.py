"""Tests for the reusable frameless window module (M1/M2)."""

import ctypes
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtCore, QtGui, QtWidgets

    from anylabeling.widgets.frameless import (
        FramelessTheme,
        FramelessWindow,
        TitleButton,
    )
    from anylabeling.widgets.frameless import hit_test, window_state

    PYQT_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional Qt dependency
    PYQT_AVAILABLE = False


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for frameless window tests"
)
class TestHitTest(unittest.TestCase):
    def test_edges(self):
        self.assertEqual(
            hit_test.edges_at(0, 0, 100, 100, 6), ("left", "top")
        )
        self.assertEqual(
            hit_test.edges_at(99, 50, 100, 100, 6), ("right",)
        )
        self.assertEqual(hit_test.edges_at(50, 99, 100, 100, 6), ("bottom",))
        self.assertEqual(hit_test.edges_at(50, 50, 100, 100, 6), ())

    def test_disabled_margin(self):
        self.assertEqual(hit_test.edges_at(0, 0, 100, 100, 0), ())

    def test_windows_codes(self):
        self.assertEqual(
            hit_test.hit_test_code(0, 0, 100, 100, 6), hit_test.HTTOPLEFT
        )
        self.assertEqual(
            hit_test.hit_test_code(99, 99, 100, 100, 6),
            hit_test.HTBOTTOMRIGHT,
        )
        self.assertEqual(
            hit_test.hit_test_code(50, 50, 100, 100, 6), hit_test.HTCLIENT
        )


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for frameless window tests"
)
class TestWindowState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or (
            QtWidgets.QApplication([])
        )
        cls.screen = QtWidgets.QApplication.primaryScreen()

    def test_clamp_keeps_visible_geometry(self):
        visible = self.screen.availableGeometry()
        rect = QtCore.QRect(visible.x() + 10, visible.y() + 10, 200, 120)
        clamped = window_state.clamp_geometry(rect, [self.screen])
        self.assertEqual(clamped, rect)

    def test_clamp_moves_offscreen_geometry(self):
        rect = QtCore.QRect(-9000, -9000, 200, 120)
        clamped = window_state.clamp_geometry(rect, [self.screen])
        self.assertTrue(self.screen.availableGeometry().intersects(clamped))

    def test_mode_helpers(self):
        restore = window_state.next_mode_after_restore
        self.assertEqual(restore("maximized"), "maximized")
        self.assertEqual(restore("normal"), "normal")


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for frameless window tests"
)
class TestFramelessTheme(unittest.TestCase):
    def test_defaults_are_complete(self):
        theme = FramelessTheme.from_mapping({})
        self.assertTrue(theme.titlebar_bg)
        self.assertTrue(theme.close_hover)
        self.assertGreater(theme.title_height, 0)

    def test_mapping_is_applied(self):
        theme = FramelessTheme.from_mapping(
            {
                "background_secondary": "#111111",
                "text": "#eeeeee",
                "surface_hover": "#222222",
                "primary": "#123456",
                "error": "#ff0000",
            }
        )
        self.assertEqual(theme.titlebar_bg, "#111111")
        self.assertEqual(theme.titlebar_text, "#eeeeee")
        self.assertEqual(theme.menubar_item_hover, "#222222")
        self.assertEqual(theme.button_primary, "#123456")
        self.assertEqual(theme.close_hover, "#ff0000")
        self.assertIn("#111111", theme.stylesheet())


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for frameless window tests"
)
class TestFramelessWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or (
            QtWidgets.QApplication([])
        )

    def tearDown(self):
        if getattr(self, "window", None) is not None:
            self.window.close()
            self.window.deleteLater()
            self.window = None

    def _make_window(self, frameless=True):
        window = FramelessWindow(frameless=frameless)
        window.setCentralWidget(QtWidgets.QLabel("content"))
        window.add_menu("File").addAction("item")
        window.add_menu("Edit").addAction("item")
        window.resize(500, 300)
        self.window = window
        return window

    def test_frameless_mode_structure(self):
        window = self._make_window(True)
        self.assertTrue(window.frameless)
        self.assertIs(window.menuBar(), window.menu_bar)
        self.assertIsNotNone(window.title_bar)
        self.assertIs(window.menu_bar.parent(), window.title_bar)
        self.assertEqual(window.menu_bar.menu_titles(), ["File", "Edit"])

    def test_native_mode_structure(self):
        window = self._make_window(False)
        self.assertFalse(window.frameless)
        self.assertIsNone(window.title_bar)
        self.assertIs(window.menuBar(), window.menu_bar)
        self.assertIs(window.menu_bar.parent(), window)

    def test_title_button_add_and_remove(self):
        window = self._make_window(True)
        clicked = []
        window.add_title_button(
            TitleButton(
                key="login",
                text="Login",
                on_clicked=lambda: clicked.append(1),
            )
        )
        button = window.title_button("login")
        self.assertIsNotNone(button)
        button.click()
        self.assertEqual(clicked, [1])
        window.remove_title_button("login")
        self.assertIsNone(window.title_button("login"))

    def test_menu_visibility_signal(self):
        window = self._make_window(True)
        seen = []
        window.menu_visibility_changed.connect(seen.append)
        window.set_menu_visible("Edit", False)
        self.assertFalse(window.menu_visibility_state()["Edit"])
        self.assertEqual(seen[-1]["Edit"], False)
        window.restore_menu_visibility({"Edit": True})
        self.assertTrue(window.menu_visibility_state()["Edit"])

    def test_title_bar_context_menu_toggles_menus(self):
        window = self._make_window(True)
        menu = window.title_bar.build_context_menu()
        texts = [action.text() for action in menu.actions()]
        self.assertIn("Menus", texts)
        submenu = next(
            action.menu()
            for action in menu.actions()
            if action.menu() is not None
        )
        self.assertEqual(
            len(submenu.actions()), len(window.menu_bar.top_level_menus())
        )
        submenu.actions()[1].trigger()
        self.assertFalse(window.menu_bar.visibility_state()["Edit"])

    def test_display_title_is_independent_from_window_title(self):
        window = self._make_window(True)
        window.set_display_title("Host App")
        window.setWindowTitle("Host App - C:/data/a.png [1/2]")
        self.assertEqual(
            window.title_bar.title_label.toolTip(), "Host App"
        )

    def test_default_application_icon_is_used(self):
        previous = self.app.windowIcon()
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtGui.QColor("#336699"))
        self.app.setWindowIcon(QtGui.QIcon(pixmap))
        try:
            window = self._make_window(True)
            self.assertFalse(window.title_bar.icon_label.isHidden())
        finally:
            self.app.setWindowIcon(previous)

    def test_native_event_never_calls_super(self):
        """Regression for fork.7: calling super() re-enters and crashes."""
        window = self._make_window(True)
        original = QtWidgets.QMainWindow.nativeEvent

        def explode(_self, *_args):
            raise AssertionError("nativeEvent must not call super()")

        QtWidgets.QMainWindow.nativeEvent = explode
        try:
            if sys.platform == "win32":
                from ctypes import wintypes

                message = wintypes.MSG()
                result = window.nativeEvent(
                    b"windows_generic_MSG", ctypes.addressof(message)
                )
            else:
                result = window.nativeEvent(b"windows_generic_MSG", 0)
        finally:
            QtWidgets.QMainWindow.nativeEvent = original
        self.assertEqual(result, (False, 0))

    def test_fullscreen_toggle_restores_window(self):
        window = self._make_window(True)
        window.show()
        self.app.processEvents()
        window.toggle_fullscreen()
        self.app.processEvents()
        self.assertTrue(window.isFullScreen())
        window.toggle_fullscreen()
        self.app.processEvents()
        self.assertFalse(window.isFullScreen())


if __name__ == "__main__":
    unittest.main()
