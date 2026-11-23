"""Image-tag vocabulary of the current file list (fork.34).

The module is Qt-free so the collection/merging rules can be tested without a
GUI.  A single :class:`TagCatalog` instance keeps the tags of every image in
the file table and can be updated incrementally after a save or a batch write;
this avoids re-reading thousands of JSON files whenever the tag library is
shown.
"""

import os.path as osp

from .file_meta import read_file_meta
from .image_tags import normalize_image_tags


def _path_key(path):
    if not path:
        return ""
    return osp.normcase(osp.abspath(str(path)))


class TagCatalog:
    """Per-image tag cache used by the "Image Attributes" tag library."""

    def __init__(self):
        self._by_path = {}

    def __len__(self):
        return len(self._by_path)

    def load(self, paths, label_file_for):
        """Sync the cache with ``paths``; only new files are read.

        Missing files and malformed annotation files contribute no tags.
        """

        wanted = []
        seen = set()
        for path in paths:
            key = _path_key(path)
            if not key or key in seen:
                continue
            seen.add(key)
            wanted.append(key)
        for key in list(self._by_path):
            if key not in seen:
                del self._by_path[key]
        for key in wanted:
            if key in self._by_path:
                continue
            try:
                meta = read_file_meta(key, label_file_for(key))
            except Exception:  # noqa: BLE001 - a bad file must not break the UI
                self._by_path[key] = ()
                continue
            self._by_path[key] = tuple(meta.tags)
        return self.entries()

    def update(self, path, tags):
        """Record the tags currently stored for ``path``."""
        key = _path_key(path)
        if not key:
            return
        self._by_path[key] = tuple(
            normalize_image_tags(
                list(tags) if isinstance(tags, (list, tuple)) else []
            )
        )

    def remove(self, paths):
        for path in paths:
            self._by_path.pop(_path_key(path), None)

    def entries(self):
        """Return ``[(tag, image_count), ...]``, most-used tags first."""
        counts = {}
        for tags in self._by_path.values():
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
        return sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0].casefold(), item[0]),
        )
