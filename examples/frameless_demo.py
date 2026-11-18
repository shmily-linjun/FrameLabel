"""Minimal demo for the reusable frameless window module.

Run from the repository root:

    python examples/frameless_demo.py

The demo uses the module without any labeling code, which is also the
copy-paste starting point for other projects.
"""

import os
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from anylabeling.widgets.frameless import (  # noqa: E402
    FramelessTheme,
    FramelessWindow,
    TitleButton,
)

LIGHT = {
    "background": "#ffffff",
    "background_secondary": "#f9f9f9",
    "surface": "#f5f5f7",
    "surface_hover": "#e5e5e5",
    "surface_pressed": "#d5d5d5",
    "border": "#e5e5e5",
    "text": "#1d1d1f",
    "text_secondary": "#86868b",
    "primary": "#0071e3",
    "primary_hover": "#0077ed",
    "primary_pressed": "#0068d0",
    "error": "#ff453a",
}


class DemoWindow(FramelessWindow):
    def __init__(self, frameless=True):
        super().__init__(frameless=frameless)
        self.set_app_title("Frameless Window Demo")
        self.set_display_title(self.tr("Frameless Window Demo"))
        self.apply_theme(FramelessTheme.from_mapping(LIGHT))

        file_menu = self.add_menu(self.tr("File"))
        file_menu.addAction(self.tr("Open"))
        file_menu.addAction(self.tr("Quit"), self.close)
        edit_menu = self.add_menu(self.tr("Edit"))
        nested = edit_menu.addMenu(self.tr("Nested"))
        nested.addMenu(self.tr("Third Level")).addAction(self.tr("Deep"))
        for title in ("View", "Tools", "Help"):
            self.add_menu(title)

        self.add_title_button(
            TitleButton(
                key="hello",
                text=self.tr("Hello"),
                tooltip=self.tr("A host button"),
                role="primary",
                on_clicked=lambda: self.statusBar().showMessage(
                    self.tr("Hello from the title bar"), 2000
                ),
            )
        )
        self.add_title_button(
            TitleButton(
                key="fullscreen",
                text=self.tr("Full"),
                tooltip=self.tr("Toggle full screen (F11)"),
                on_clicked=self.toggle_fullscreen,
            )
        )

        label = QtWidgets.QLabel(
            self.tr(
                "Drag the title bar to move, drag the edges to resize, "
                "double-click to maximize. Right-click the menu bar to "
                "hide/show menus."
            )
        )
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        self.set_content_widget(label)
        self.statusBar().showMessage(self.tr("Ready"))
        self.resize(900, 600)


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = DemoWindow(frameless=True)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
