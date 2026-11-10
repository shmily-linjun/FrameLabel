"""Tests for the asynchronous thumbnail loader."""

import os
import pathlib
import shutil
import time
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.utils import thumbnail as thumbnail_module
from anylabeling.views.labeling.utils.thumbnail import ThumbnailLoader

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TEMPORARY_ROOT = _REPO_ROOT / "temporary" / "pytest-utils"


@pytest.fixture()
def work_dir():
    # The pytest ``tmp_path`` fixture creates directories with mode 0o700,
    # which the Windows sandbox used for this repository cannot access; keep
    # all temporary files under the repository's own ``temporary`` folder
    # instead.
    directory = _TEMPORARY_ROOT / uuid.uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            _TEMPORARY_ROOT.rmdir()
        except OSError:
            pass


@pytest.fixture()
def app():
    application = QtWidgets.QApplication.instance()
    if application is None:
        application = QtWidgets.QApplication([])
    yield application


def _wait_until(predicate, timeout=5.0):
    application = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if application is not None:
            application.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    if application is not None:
        application.processEvents()
    return predicate()


def _make_image(directory, name="image.png", size=(64, 48)):
    path = directory / name
    Image.new("RGB", size, "red").save(path)
    return str(path)


def test_request_loads_asynchronously_then_returns_cached_pixmap(
    app, work_dir
):
    path = _make_image(work_dir)
    loader = ThumbnailLoader(size=16, max_threads=2)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append((image_path, pixmap))
    )
    try:
        assert loader.request(path) is None
        assert _wait_until(lambda: len(received) == 1)

        signal_path, pixmap = received[0]
        assert signal_path == path
        assert not pixmap.isNull()
        assert (pixmap.width(), pixmap.height()) == (16, 12)

        cached = loader.request(path)
        assert cached is not None
        assert (cached.width(), cached.height()) == (16, 12)

        # A cache hit must not emit the signal (and therefore schedule no
        # second background load).
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()
        assert len(received) == 1
    finally:
        loader.shutdown()


def test_signal_is_emitted_from_loader_thread(app, work_dir):
    path = _make_image(work_dir)
    loader = ThumbnailLoader(size=16)
    threads = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: threads.append(
            QtCore.QThread.currentThread()
        )
    )
    try:
        loader.request(path)
        assert _wait_until(lambda: len(threads) == 1)
        assert threads[0] == app.thread()
    finally:
        loader.shutdown()


def test_pending_requests_for_same_path_are_deduplicated(
    app, work_dir, monkeypatch
):
    path = _make_image(work_dir)
    calls = []
    original_loader = thumbnail_module._load_scaled_qimage

    def slow_loader(image_path, size):
        calls.append(image_path)
        time.sleep(0.2)
        return original_loader(image_path, size)

    monkeypatch.setattr(
        thumbnail_module, "_load_scaled_qimage", slow_loader
    )
    loader = ThumbnailLoader(size=16)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append(image_path)
    )
    try:
        assert loader.request(path) is None
        # The first request is still running, so this one is deduplicated.
        assert loader.request(path) is None
        assert _wait_until(lambda: len(received) == 1)
        assert calls == [path]
        assert loader.request(path) is not None
    finally:
        loader.shutdown()


def test_failed_path_is_recorded_and_not_retried(app, work_dir, monkeypatch):
    missing = str(work_dir / "missing.png")
    calls = []
    original_loader = thumbnail_module._load_scaled_qimage

    def counting_loader(image_path, size):
        calls.append(image_path)
        return original_loader(image_path, size)

    monkeypatch.setattr(
        thumbnail_module, "_load_scaled_qimage", counting_loader
    )
    loader = ThumbnailLoader(size=16)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append(image_path)
    )
    try:
        assert loader.request(missing) is None
        assert _wait_until(lambda: missing in loader._failed)
        assert loader.request(missing) is None

        app.processEvents()
        time.sleep(0.05)
        app.processEvents()
        assert calls == [missing]
        assert received == []
    finally:
        loader.shutdown()


def test_clear_forces_reload_and_resets_failures(app, work_dir):
    path = _make_image(work_dir)
    missing = str(work_dir / "missing.png")
    loader = ThumbnailLoader(size=16)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append(image_path)
    )
    try:
        loader.request(path)
        assert _wait_until(lambda: received == [path])
        loader.request(missing)
        assert _wait_until(lambda: missing in loader._failed)

        loader.clear()
        assert missing not in loader._failed
        assert loader.request(path) is None
        assert _wait_until(lambda: len(received) == 2)
        assert received[1] == path
    finally:
        loader.shutdown()


def test_shutdown_stops_workers_and_ignores_new_requests(app, work_dir):
    path = _make_image(work_dir)
    loader = ThumbnailLoader(size=16)
    loader.request(path)
    loader.shutdown()

    assert loader._shutdown is True
    assert loader._pool.activeThreadCount() == 0
    assert loader.request(path) is None
    # Calling shutdown twice must be harmless.
    loader.shutdown()


def test_exif_orientation_is_applied(app, work_dir):
    path = work_dir / "oriented.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise when displayed
    Image.new("RGB", (40, 20), "blue").save(path, exif=exif.tobytes())

    loader = ThumbnailLoader(size=16)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append(pixmap)
    )
    try:
        loader.request(str(path))
        assert _wait_until(lambda: len(received) == 1)
        pixmap = received[0]
        assert (pixmap.width(), pixmap.height()) == (8, 16)
    finally:
        loader.shutdown()


def test_clear_discards_result_of_in_flight_load(
    app, work_dir, monkeypatch
):
    path = _make_image(work_dir)
    calls = []
    original_loader = thumbnail_module._load_scaled_qimage

    def slow_loader(image_path, size):
        calls.append(image_path)
        time.sleep(0.2)
        return original_loader(image_path, size)

    monkeypatch.setattr(
        thumbnail_module, "_load_scaled_qimage", slow_loader
    )
    loader = ThumbnailLoader(size=16)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append(image_path)
    )
    try:
        loader.request(path)
        assert _wait_until(lambda: len(calls) == 1)
        loader.clear()
        assert loader.request(path) is None
        assert _wait_until(lambda: len(received) == 1)
        # Only the load started after clear() may publish its result.
        assert received == [path]
        assert len(calls) == 2
    finally:
        loader.shutdown()


def test_cache_respects_entry_limit(app, work_dir, monkeypatch):
    monkeypatch.setattr(thumbnail_module, "_CACHE_MAX_ENTRIES", 1)
    first = _make_image(work_dir, "first.png", size=(8, 8))
    second = _make_image(work_dir, "second.png", size=(8, 8))
    loader = ThumbnailLoader(size=8)
    received = []
    loader.thumbnail_ready.connect(
        lambda image_path, pixmap: received.append(image_path)
    )
    try:
        loader.request(first)
        assert _wait_until(lambda: len(received) == 1)
        loader.request(second)
        assert _wait_until(lambda: len(received) == 2)

        # The first entry was evicted, so it has to be loaded again.
        assert loader.request(first) is None
        assert _wait_until(lambda: len(received) == 3)
        assert received[2] == first
    finally:
        loader.shutdown()


def test_request_ignores_empty_path(app):
    loader = ThumbnailLoader()
    try:
        assert loader.request(None) is None
        assert loader.request("") is None
    finally:
        loader.shutdown()
