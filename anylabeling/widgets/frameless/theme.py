"""Colors and metrics for the frameless window chrome.

The host application owns theming; this module only maps its color roles to
the chrome widgets.  Keeping the mapping here means the module can be copied
into another project with a different palette by passing a mapping.
"""

from __future__ import annotations

import dataclasses
from typing import Mapping, Optional

DEFAULT_TITLE_HEIGHT = 30
DEFAULT_WINDOW_BUTTON_WIDTH = 42
DEFAULT_RESIZE_MARGIN = 6
DEFAULT_ICON_SIZE = 16


@dataclasses.dataclass(frozen=True)
class FramelessTheme:
    """Resolved colors and metrics used by the chrome widgets."""

    titlebar_bg: str = "#ffffff"
    titlebar_text: str = "#1d1d1f"
    titlebar_text_inactive: str = "#86868b"
    titlebar_border: str = "#E5E5E5"
    menubar_bg: str = "#ffffff"
    menubar_text: str = "#1d1d1f"
    menubar_item_hover: str = "#e5e5e5"
    menubar_item_pressed: str = "#d5d5d5"
    button_bg: str = "#f5f5f7"
    button_bg_hover: str = "#e5e5e5"
    button_bg_pressed: str = "#d5d5d5"
    button_text: str = "#1d1d1f"
    button_primary: str = "#0071e3"
    button_primary_hover: str = "#0077ED"
    button_primary_pressed: str = "#0068D0"
    button_primary_text: str = "#ffffff"
    close_hover: str = "#FF453A"
    close_pressed: str = "#d70015"
    title_height: int = DEFAULT_TITLE_HEIGHT
    window_button_width: int = DEFAULT_WINDOW_BUTTON_WIDTH
    resize_margin: int = DEFAULT_RESIZE_MARGIN
    icon_size: int = DEFAULT_ICON_SIZE

    @classmethod
    def from_mapping(
        cls, mapping: Optional[Mapping[str, str]]
    ) -> "FramelessTheme":
        """Build a theme from the host color roles.

        Recognized keys mirror the project's ``theme.py`` dictionary
        (``background``, ``background_secondary``, ``surface``,
        ``surface_hover``, ``surface_pressed``, ``border``, ``text``,
        ``text_secondary``, ``primary``, ``primary_hover``,
        ``primary_pressed``, ``error``).
        Unknown host roles are ignored; missing ones keep these defaults.
        """
        if not mapping:
            return cls()
        get = mapping.get
        titlebar_bg = get("background_secondary") or get("background")
        button_bg = get("surface")
        return cls(
            titlebar_bg=titlebar_bg or cls.titlebar_bg,
            titlebar_text=get("text") or cls.titlebar_text,
            titlebar_text_inactive=(
                get("text_secondary") or cls.titlebar_text_inactive
            ),
            titlebar_border=get("border") or cls.titlebar_border,
            menubar_bg=titlebar_bg or cls.menubar_bg,
            menubar_text=get("text") or cls.menubar_text,
            menubar_item_hover=(
                get("surface_hover") or cls.menubar_item_hover
            ),
            menubar_item_pressed=(
                get("surface_pressed") or cls.menubar_item_pressed
            ),
            button_bg=button_bg or cls.button_bg,
            button_bg_hover=get("surface_hover") or cls.button_bg_hover,
            button_bg_pressed=(
                get("surface_pressed") or cls.button_bg_pressed
            ),
            button_text=get("text") or cls.button_text,
            button_primary=get("primary") or cls.button_primary,
            button_primary_hover=(
                get("primary_hover") or cls.button_primary_hover
            ),
            button_primary_pressed=(
                get("primary_pressed") or cls.button_primary_pressed
            ),
            button_primary_text=cls.button_primary_text,
            close_hover=get("error") or cls.close_hover,
            close_pressed=cls.close_pressed,
        )

    def stylesheet(self) -> str:
        """Return the QSS for the chrome widgets."""
        return f"""
            QWidget#FramelessTitleBar {{
                background-color: {self.titlebar_bg};
                border-bottom: 1px solid {self.titlebar_border};
            }}
            QLabel#FramelessTitleIcon {{
                background: transparent;
            }}
            QLabel#FramelessTitleText {{
                color: {self.titlebar_text};
                background: transparent;
                font-size: 12px;
                padding: 0 4px;
            }}
            QLabel#FramelessTitleText[inactive="true"] {{
                color: {self.titlebar_text_inactive};
            }}
            QMenuBar#FramelessMenuBar {{
                background: transparent;
                color: {self.menubar_text};
                border: none;
                padding: 0;
            }}
            QMenuBar#FramelessMenuBar::item {{
                background: transparent;
                padding: 2px 8px;
                border-radius: 4px;
            }}
            QMenuBar#FramelessMenuBar::item:selected {{
                background-color: {self.menubar_item_hover};
            }}
            QMenuBar#FramelessMenuBar::item:pressed {{
                background-color: {self.menubar_item_pressed};
            }}
            QToolButton#FramelessWindowButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QToolButton#FramelessWindowButton:hover {{
                background-color: {self.button_bg_hover};
            }}
            QToolButton#FramelessWindowButton:pressed {{
                background-color: {self.button_bg_pressed};
            }}
            QToolButton#FramelessCloseButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QToolButton#FramelessCloseButton:hover {{
                background-color: {self.close_hover};
            }}
            QToolButton#FramelessCloseButton:pressed {{
                background-color: {self.close_pressed};
            }}
            QToolButton#FramelessTitleButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 2px 8px;
                color: {self.button_text};
                font-size: 12px;
            }}
            QToolButton#FramelessTitleButton:hover {{
                background-color: {self.button_bg_hover};
            }}
            QToolButton#FramelessTitleButton:pressed {{
                background-color: {self.button_bg_pressed};
            }}
            QToolButton#FramelessTitleButton[primary="true"] {{
                background-color: {self.button_primary};
                border: none;
                color: {self.button_primary_text};
            }}
            QToolButton#FramelessTitleButton[primary="true"]:hover {{
                background-color: {self.button_primary_hover};
            }}
            QToolButton#FramelessTitleButton[primary="true"]:pressed {{
                background-color: {self.button_primary_pressed};
            }}
        """
