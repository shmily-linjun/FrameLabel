"""Right side tab visibility and statistics refresh.

The right sidebar hosts the objects/classes/flags/description/statistics tabs
and shares the file table below them.  Which tabs are shown, their context
menu, and the click-to-filter behaviour of the statistics table belong
together; they used to live on ``LabelingWidget``.

The host (``LabelingWidget``) owns the tab widget, the statistics table, the
file table controller and the search bar; this class is stateless.
"""

from PyQt6 import QtWidgets

import os.path as osp

from .logger import logger
from .utils.dataset_statistics import FileStatisticsEntry
from .utils.file_search import escape_query_value

#: Tabs that may not be hidden.  The "Image Attributes" tab is the only place
#: where image tags and image flags are edited, so hiding it would leave that
#: metadata without any UI.
ALWAYS_VISIBLE_TABS = ("flags",)


class RightSidebarTabs:
    """Right panel tab visibility and statistics filtering."""

    def __init__(self, host):
        self.host = host

    def _tab_key_for_page(self, page):
        for key, _title, candidate in self.host._tab_pages:
            if candidate is page:
                return key
        return None

    def _rebuild_right_tabs(self):
        tabs = getattr(self.host, "right_tabs", None)
        if tabs is None:
            return
        pages = getattr(self.host, "_tab_pages", ())
        current_page = tabs.currentWidget()
        tabs.blockSignals(True)
        try:
            while tabs.count():
                tabs.removeTab(0)
            for key, title, page in pages:
                if key in self.host._hidden_tabs:
                    continue
                page.setParent(tabs)
                tabs.addTab(page, title)
            if current_page is not None and tabs.indexOf(current_page) >= 0:
                tabs.setCurrentWidget(current_page)
        finally:
            tabs.blockSignals(False)

    def _apply_right_tabs_config(self):
        pages = getattr(self.host, "_tab_pages", ())
        valid_keys = {key for key, _title, _page in pages}
        section = self.host._config.get("right_tabs")
        hidden = section.get("hidden") if isinstance(section, dict) else None
        hidden_keys = []
        if isinstance(hidden, (list, tuple)):
            hidden_keys = [
                str(item) for item in hidden if str(item) in valid_keys
            ]
        elif isinstance(hidden, str):
            hidden_keys = [hidden] if hidden in valid_keys else []
        hidden_keys = [key for key in hidden_keys if key in valid_keys]
        hidden_keys = [
            key for key in hidden_keys if key not in ALWAYS_VISIBLE_TABS
        ]
        if len(hidden_keys) >= len(valid_keys) and valid_keys:
            hidden_keys = sorted(valid_keys - {pages[0][0]})
        self.host._hidden_tabs = set(hidden_keys)
        self.host._rebuild_right_tabs()

    def set_right_tab_visible(self, key, visible):
        pages = getattr(self.host, "_tab_pages", ())
        valid_keys = {page_key for page_key, _title, _page in pages}
        if key not in valid_keys:
            return
        if not visible and key in ALWAYS_VISIBLE_TABS:
            self.host.status(self.host.tr("This panel cannot be hidden"))
            return
        hidden = set(self.host._hidden_tabs)
        if visible:
            hidden.discard(key)
        else:
            if len(valid_keys) - len(hidden) <= 1:
                self.host.status(self.host.tr("At least one panel must stay visible"))
                return
            hidden.add(key)
        self.host._hidden_tabs = hidden
        self.host._rebuild_right_tabs()
        section = self.host._config.setdefault("right_tabs", {})
        if isinstance(section, dict):
            section["hidden"] = sorted(self.host._hidden_tabs)

    def show_right_tab(self, key):
        if key in self.host._hidden_tabs:
            self.host.set_right_tab_visible(key, True)
        pages = getattr(self.host, "_tab_pages", ())
        for page_key, _title, page in pages:
            if page_key != key:
                continue
            index = self.host.right_tabs.indexOf(page)
            if index >= 0:
                self.host.right_tabs.setCurrentIndex(index)
            return

    def pop_right_tabs_menu(self, point):
        if not hasattr(self.host, "right_tabs"):
            return
        menu = QtWidgets.QMenu(self.host.right_tabs)
        for key, title, _page in self.host._tab_pages:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(key not in self.host._hidden_tabs)
            action.setData(key)
        chosen = menu.exec(self.host.right_tabs.tabBar().mapToGlobal(point))
        if chosen is None:
            return
        self.host.set_right_tab_visible(chosen.data(), chosen.isChecked())

    def show_flags_page(self):
        self.host.show_right_tab("flags")

    def _on_right_tab_changed(self, _index):
        page = self.host.right_tabs.currentWidget()
        if page is getattr(self.host, "label_manager_widget", None):
            page.ensure_built()
            return
        if page is getattr(self.host, "statistics_table", None):
            self.host._refresh_statistics()

    def _refresh_statistics(self):
        table = getattr(self.host, "statistics_table", None)
        if table is None:
            return
        try:
            repository = getattr(self.host, "dataset_repository", None)
            if repository is not None:
                root = self.host.dataset_root or ""
                entries = [
                    FileStatisticsEntry(
                        path=osp.join(root, row["path"]),
                        split=row["split"],
                        labels=tuple(row["labels"]),
                    )
                    for row in repository.statistics_rows()
                ]
                table.set_entries(entries)
            else:
                table.refresh(self.host.image_list, self.host.output_dir)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to refresh statistics table", exc_info=True)

    def _refresh_statistics_if_visible(self):
        table = getattr(self.host, "statistics_table", None)
        if table is None or self.host.right_tabs.currentWidget() is not table:
            return
        self.host._refresh_statistics()

    def _on_statistics_filter_requested(self, statistics_filter):
        """Turn a statistics-table click into a search query."""
        parts = []
        if statistics_filter.objectless:
            parts.append("shape::0")
        elif statistics_filter.label:
            parts.append(
                "label::" + escape_query_value(statistics_filter.label)
            )
        if statistics_filter.split:
            parts.append("split::" + statistics_filter.split)
        if not parts:
            return
        self.host.file_search.setText(",".join(parts))
        self.host.file_search_changed()
