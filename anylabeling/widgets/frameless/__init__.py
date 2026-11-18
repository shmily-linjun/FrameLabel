"""Reusable frameless window chrome for PyQt6 desktop applications.

The package is intentionally independent from the labeling application: it
only imports PyQt6 and the standard library, takes its colors from a plain
mapping, and exposes menu, title-button and window-state APIs that any
PyQt6 project can use.

See ``docs/dev/无边框窗口模块-讨论稿.md`` for the agreed scope and the known
platform limitations.
"""

from .window import FramelessWindow
from .theme import FramelessTheme
from .title_bar import TitleBar, TitleButton
from .menu_bar import FrameMenuBar
from .window_buttons import WindowButton

__all__ = [
    "FramelessWindow",
    "FramelessTheme",
    "FrameMenuBar",
    "TitleBar",
    "TitleButton",
    "WindowButton",
]
