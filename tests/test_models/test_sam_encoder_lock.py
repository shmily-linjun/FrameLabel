"""CPU encoder serialisation for the SAM-family adapters.

The labeling app preloads the next files in a background thread, so two
encoder sessions used to run concurrently.  A SAM ViT encoder peaks around
5 GiB, which made ONNX Runtime fail to allocate the 1 GiB attention buffer on
memory-constrained machines.  These tests pin the contract:

* CPU-only provider lists share one lock (one encoder at a time);
* accelerator provider lists keep the previous parallel behaviour;
* two concurrent ``run_encoder`` calls never overlap on CPU.
"""

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from anylabeling.services.auto_labeling import sam_onnx
    from anylabeling.services.auto_labeling.encoder_lock import (
        cpu_encoder_lock,
    )

    AVAILABLE = True
except Exception:  # pragma: no cover - PyQt6/onnxruntime may be missing
    AVAILABLE = False


class _FakeSession:
    """Collects overlap information for concurrent ``run`` calls."""

    active = 0
    max_active = 0
    calls = 0
    gate = threading.Lock()

    def __init__(self, *_args, **_kwargs):
        pass

    def get_inputs(self):
        return [SimpleNamespace(name="input_image")]

    def run(self, _output_names, _feed):
        with _FakeSession.gate:
            _FakeSession.active += 1
            _FakeSession.calls += 1
            _FakeSession.max_active = max(
                _FakeSession.max_active, _FakeSession.active
            )
        try:
            time.sleep(0.08)
        finally:
            with _FakeSession.gate:
                _FakeSession.active -= 1
        return [np.zeros((1, 256, 64, 64), dtype=np.float32)]


def _reset_fake():
    with _FakeSession.gate:
        _FakeSession.active = 0
        _FakeSession.max_active = 0
        _FakeSession.calls = 0


@unittest.skipUnless(
    AVAILABLE, "PyQt6 and onnxruntime are required for SAM encoder tests"
)
class TestCpuEncoderLock(unittest.TestCase):
    def test_cpu_only_providers_share_one_lock(self):
        first = cpu_encoder_lock(["CPUExecutionProvider"])
        second = cpu_encoder_lock(
            ["AzureExecutionProvider", "CPUExecutionProvider"]
        )
        self.assertIs(first, second)

    def test_accelerator_providers_are_not_serialised(self):
        context = cpu_encoder_lock(
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        self.assertFalse(hasattr(context, "acquire"))

    def test_two_concurrent_encodes_do_not_overlap_on_cpu(self):
        _reset_fake()
        with patch.object(
            sam_onnx.onnxruntime,
            "get_available_providers",
            return_value=["CPUExecutionProvider"],
        ), patch.object(
            sam_onnx.onnxruntime, "InferenceSession", _FakeSession
        ):
            model = sam_onnx.SegmentAnythingONNX("encoder.onnx", "decoder.onnx")
            feeds = {
                "input_image": np.zeros((684, 1024, 3), dtype=np.float32)
            }
            threads = [
                threading.Thread(
                    target=model.run_encoder, args=(feeds,)
                )
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertEqual(_FakeSession.calls, 2)
        self.assertEqual(_FakeSession.max_active, 1)

    def test_session_is_released_after_encode(self):
        _reset_fake()
        with patch.object(
            sam_onnx.onnxruntime,
            "get_available_providers",
            return_value=["CPUExecutionProvider"],
        ), patch.object(
            sam_onnx.onnxruntime, "InferenceSession", _FakeSession
        ):
            model = sam_onnx.SegmentAnythingONNX("encoder.onnx", "decoder.onnx")
            model.run_encoder(
                {"input_image": np.zeros((684, 1024, 3), dtype=np.float32)}
            )
            self.assertIsNone(model.encoder_session)


if __name__ == "__main__":
    unittest.main()
