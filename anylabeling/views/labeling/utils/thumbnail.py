"""Asynchronous thumbnail loading helpers.

The loader decodes images on a thread pool and hands the resulting
``QPixmap`` back to the GUI thread through :attr:`ThumbnailLoader.thumbnail_ready`.
Only :class:`~PyQt6.QtGui.QImage` objects are created on worker threads;
:class:`~PyQt6.QtGui.QPixmap` instances (which require a GUI thread) are
converted and cached on the thread that owns the loader.
"""

import os
from collections import OrderedDict

from PyQt6 import QtCore, QtGui

THUMBNAIL_SIZE = 32
_CACHE_MAX_ENTRIES = 2000
_POOL_SHUTDOWN_TIMEOUT_MS = 5000


def _load_scaled_qimage(image_path, size):
    """Decode ``image_path`` into a scaled ``QImage`` (worker thread only).

    Returns a null :class:`~PyQt6.QtGui.QImage` when the file cannot be read.
    The requested ``size`` is the maximum edge length; the aspect ratio is
    preserved and EXIF orientation is applied by the reader.
    """
    reader = QtGui.QImageReader(str(image_path))
    reader.setAutoTransform(True)
    if size and size > 0:
        source_size = reader.size()
        if source_size.isValid() and not source_size.isEmpty():
            scaled_size = source_size.scaled(
                QtCore.QSize(size, size),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            )
            if scaled_size.isValid() and not scaled_size.isEmpty():
                reader.setScaledSize(scaled_size)
    if not reader.canRead():
        return QtGui.QImage()
    return reader.read()


class _TaskSignals(QtCore.QObject):
    """Signal carrier used to hop a decoded image back to the GUI thread."""

    finished = QtCore.pyqtSignal(str, QtGui.QImage, int)


class _ThumbnailRunnable(QtCore.QRunnable):
    """Decode one image on a worker thread and signal the loader."""

    def __init__(self, image_path, size, signals, generation):
        super().__init__()
        self._image_path = image_path
        self._size = size
        self._signals = signals
        self._generation = generation
        self.setAutoDelete(True)

    def run(self):
        image = QtGui.QImage()
        try:
            image = _load_scaled_qimage(self._image_path, self._size)
        except Exception:  # pragma: no cover - defensive
            image = QtGui.QImage()
        try:
            self._signals.finished.emit(
                self._image_path, image, self._generation
            )
        except RuntimeError:  # pragma: no cover - loader already torn down
            pass


class ThumbnailLoader(QtCore.QObject):
    """Load image thumbnails asynchronously and cache them by path.

    ``request()`` returns an already cached pixmap immediately, or returns
    ``None`` and schedules a background job. Once decoding finishes the
    ``thumbnail_ready(image_path, pixmap)`` signal is emitted from the thread
    that owns the loader (normally the GUI thread). Paths that failed to load
    are remembered and are not retried until :meth:`clear` is called.
    """

    thumbnail_ready = QtCore.pyqtSignal(str, QtGui.QPixmap)

    def __init__(self, parent=None, size=THUMBNAIL_SIZE, max_threads=4):
        super().__init__(parent)
        try:
            self._size = max(1, int(size))
        except (TypeError, ValueError):
            self._size = THUMBNAIL_SIZE
        try:
            thread_count = max(1, int(max_threads))
        except (TypeError, ValueError):
            thread_count = 1
        self._shutdown = False
        self._generation = 0
        self._cache = OrderedDict()
        self._failed = set()
        # image_path -> generation of the in-flight request
        self._pending = {}
        # (image_path, generation) -> (signals, runnable); keeps the Python
        # wrappers alive until their result has been handled.
        self._tasks = {}
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(thread_count)

    # -- public API -----------------------------------------------------
    def request(self, image_path):
        """Return a cached ``QPixmap`` or schedule a background load."""
        key = self._normalize_path(image_path)
        if not key or self._shutdown:
            return None

        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return QtGui.QPixmap(cached)

        if key in self._failed or key in self._pending:
            return None

        generation = self._generation
        self._pending[key] = generation
        signals = _TaskSignals()
        runnable = _ThumbnailRunnable(key, self._size, signals, generation)
        signals.finished.connect(self._on_task_finished)
        self._tasks[(key, generation)] = (signals, runnable)
        self._pool.start(runnable)
        return None

    def clear(self):
        """Drop cached and failed entries so later requests reload images.

        Decoding already in progress is not interrupted; its result is
        discarded because the generation counter is bumped.
        """
        self._generation += 1
        self._cache.clear()
        self._failed.clear()
        self._pending.clear()

    def shutdown(self):
        """Stop accepting requests and wait for worker threads to finish."""
        if self._shutdown:
            return
        self._shutdown = True
        self._generation += 1
        self._pending.clear()
        self._pool.clear()
        if self._pool.waitForDone(_POOL_SHUTDOWN_TIMEOUT_MS):
            self._tasks.clear()
        self._cache.clear()
        self._failed.clear()

    # -- internal helpers ----------------------------------------------
    def _on_task_finished(self, image_path, image, generation):
        self._tasks.pop((image_path, generation), None)
        if self._pending.get(image_path) == generation:
            del self._pending[image_path]

        if self._shutdown or generation != self._generation:
            return

        if image is None or image.isNull():
            self._failed.add(image_path)
            return

        pixmap = QtGui.QPixmap.fromImage(image)
        if pixmap.isNull():
            self._failed.add(image_path)
            return

        self._cache[image_path] = pixmap
        self._cache.move_to_end(image_path)
        while len(self._cache) > _CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        self.thumbnail_ready.emit(image_path, pixmap)

    @staticmethod
    def _normalize_path(image_path):
        if image_path is None:
            return ""
        try:
            path = os.fspath(image_path)
        except TypeError:
            path = image_path
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, str):
            path = str(path)
        return path

    def __del__(self):
        try:
            self.shutdown()
        except Exception:  # pragma: no cover - interpreter teardown
            pass
