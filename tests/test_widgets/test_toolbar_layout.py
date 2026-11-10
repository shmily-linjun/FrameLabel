import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtCore, QtGui, QtWidgets

    import anylabeling.resources.resources  # noqa: F401
    from anylabeling.views.labeling.utils.theme import init_theme
    from anylabeling.views.labeling.widgets.toolbar import ToolBar

    PYQT_AVAILABLE = True
except Exception:
    PYQT_AVAILABLE = False


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt6 is required for toolbar tests")
class TestToolBarLayout(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance()
        if self.app is None:
            self.app = QtWidgets.QApplication([])
        self._widgets = []

    def tearDown(self):
        for widget in self._widgets:
            widget.close()
        init_theme("light")
        self.app.processEvents()

    def test_toolbar_is_a_dockable_q_toolbar(self):
        toolbar = ToolBar("Tools")
        self._widgets.append(toolbar)

        self.assertIsInstance(toolbar, QtWidgets.QToolBar)
        self.assertEqual(toolbar.objectName(), "ToolsToolBar")
        areas = toolbar.allowedAreas()
        self.assertTrue(bool(areas & QtCore.Qt.ToolBarArea.TopToolBarArea))
        self.assertTrue(bool(areas & QtCore.Qt.ToolBarArea.LeftToolBarArea))
        self.assertTrue(toolbar.isMovable())
        # Floating is disabled on purpose: Qt 6 mis-sizes the floating window
        # on Windows; docking at the top/left is supported instead.
        self.assertFalse(toolbar.isFloatable())

    def test_main_window_supports_top_and_left_dock_areas(self):
        window = QtWidgets.QMainWindow()
        self._widgets.append(window)
        toolbar = ToolBar("Tools")
        window.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
        window.resize(800, 600)
        window.show()
        self.app.processEvents()
        self.assertEqual(
            window.toolBarArea(toolbar),
            QtCore.Qt.ToolBarArea.TopToolBarArea,
        )

        window.addToolBar(QtCore.Qt.ToolBarArea.LeftToolBarArea, toolbar)
        self.app.processEvents()
        self.assertEqual(
            window.toolBarArea(toolbar),
            QtCore.Qt.ToolBarArea.LeftToolBarArea,
        )
        self.assertEqual(
            toolbar.orientation(), QtCore.Qt.Orientation.Vertical
        )

    def test_scaled_toolbar_rebuilds_actions(self):
        for mode in ("light", "dark"):
            init_theme(mode)
            toolbar = ToolBar("Tools")
            self._widgets.append(toolbar)
            toolbar.addAction(QtGui.QAction("Open", toolbar))
            toolbar.setUiScale(1.5)
            toolbar.clear()
            toolbar.addAction(QtGui.QAction("Save", toolbar))
            toolbar.resize(600, 40)
            toolbar.show()
            self.app.processEvents()

            self.assertEqual(len(toolbar.actions()), 1)
            buttons = [
                button
                for button in toolbar.findChildren(QtWidgets.QToolButton)
                if button.defaultAction() is not None
            ]
            self.assertEqual(len(buttons), 1)
            self.assertEqual(
                buttons[0].iconSize(), QtCore.QSize(27, 27)
            )
