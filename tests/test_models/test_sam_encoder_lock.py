"""SAM-family encoder safety rules.

Two rules are pinned here:

* CPU-only provider lists share one lock (one encoder at a time), because a
  SEM ViT encoder peaks around 5 GiB and the labeling app can otherwise run the
  preload thread and an interactive encode at the same time;
* encoder outputs are copied out of the ONNX Runtime arena before the session
  is released.  ORT returns views (``owndata`` is False); caching such a view
  per image pins the whole ~4 GB arena even after the session is closed.
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
    from anylabeling.services.auto_labeling import sam_hq, sam_onnx
    from anylabeling.services.auto_labeling.encoder_lock import (
        cpu_encoder_lock,
    )

    AVAILABLE = True
except Exception:  # pragma: no cover - PyQt6/onnxruntime may be missing
    AVAILABLE = False

EMBEDDING = np.zeros((1, 256, 64, 64), dtype=np.float32)
INTERMEDIATE = np.zeros((1, 2, 3, 4), dtype=np.float32)


class _FakeSession:
    """Fake ORT session that reports overlapping ``run`` calls.

    ``run`` returns non-owning views, mimicking the real ORT behaviour where
    graph outputs live in the session arena.
    """

    active = 0
    max_active = 0
    calls = 0
    gate = threading.Lock()
    outputs = [EMBEDDING]

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
        # Slices are views: owndata is False, like ORT graph outputs.
        return [output[:] for output in _FakeSession.outputs]


def _reset_fake():
    with _FakeSession.gate:
        _FakeSession.active = 0
        _FakeSession.max_active = 0
        _FakeSession.calls = 0
    _FakeSession.outputs = [EMBEDDING]


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
                threading.Thread(target=model.run_encoder, args=(feeds,))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertEqual(_FakeSession.calls, 2)
        self.assertEqual(_FakeSession.max_active, 1)


@unittest.skipUnless(
    AVAILABLE, "PyQt6 and onnxruntime are required for SAM encoder tests"
)
class TestEncoderOutputIsCopied(unittest.TestCase):
    def test_sam_onnx_output_owns_its_data(self):
        _reset_fake()
        with patch.object(
            sam_onnx.onnxruntime,
            "get_available_providers",
            return_value=["CPUExecutionProvider"],
        ), patch.object(
            sam_onnx.onnxruntime, "InferenceSession", _FakeSession
        ):
            model = sam_onnx.SegmentAnythingONNX("encoder.onnx", "decoder.onnx")
            embedding = model.run_encoder(
                {"input_image": np.zeros((684, 1024, 3), dtype=np.float32)}
            )
            self.assertIsNone(model.encoder_session)

        self.assertTrue(embedding.flags.owndata)
        self.assertFalse(np.shares_memory(embedding, EMBEDDING))

    def test_sam_hq_encoder_output_owns_its_data(self):
        _reset_fake()
        _FakeSession.outputs = [EMBEDDING, INTERMEDIATE]
        with patch.object(
            sam_hq.onnxruntime,
            "get_available_providers",
            return_value=["CPUExecutionProvider"],
        ), patch.object(
            sam_hq.onnxruntime, "InferenceSession", _FakeSession
        ):
            model = sam_hq.SegmentAnythingONNX("encoder.onnx", "decoder.onnx")
            embeddings, interms = model.run_encoder(
                {"input_image": np.zeros((684, 1024, 3), dtype=np.float32)}
            )
            self.assertIsNone(model.encoder_session)

        self.assertTrue(embeddings.flags.owndata)
        self.assertFalse(np.shares_memory(embeddings, EMBEDDING))
        self.assertTrue(interms.flags.owndata)

    def test_repeated_encodes_do_not_retain_session(self):
        _reset_fake()
        with patch.object(
            sam_onnx.onnxruntime,
            "get_available_providers",
            return_value=["CPUExecutionProvider"],
        ), patch.object(
            sam_onnx.onnxruntime, "InferenceSession", _FakeSession
        ):
            model = sam_onnx.SegmentAnythingONNX("encoder.onnx", "decoder.onnx")
            embeddings = [
                model.run_encoder(
                    {
                        "input_image": np.zeros(
                            (684, 1024, 3), dtype=np.float32
                        )
                    }
                )
                for _ in range(3)
            ]
        self.assertEqual(len(embeddings), 3)
        for embedding in embeddings:
            self.assertTrue(embedding.flags.owndata)


if __name__ == "__main__":
    unittest.main()
