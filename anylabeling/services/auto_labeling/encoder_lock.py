"""Serialise heavy Segment-Anything encoder runs on CPU-only inference.

The labeling app preloads the next files in a background thread while the user
can trigger an encode from the main thread.  A Segment-Anything ViT encoder
needs about 5 GiB at peak on CPU (the global attention matrix alone is a 1 GiB
allocation), so two concurrent encoders peak above 10 GiB and can fail with
``BFCArena ... Failed to allocate memory``.  Preloading is a UX optimisation,
not a correctness requirement: serialising the encoder keeps the peak at one
encode and simply lets the preload thread wait.

GPU providers keep the previous behaviour: preloading still helps there and
the memory pressure model is different.
"""

import contextlib
import threading

_CPU_ONLY_PROVIDERS = frozenset(
    {"CPUExecutionProvider", "AzureExecutionProvider"}
)

#: Shared across every SAM-family adapter in the process: only one CPU encoder
#: run at a time, regardless of which adapter instance started it.
_ENCODER_LOCK = threading.Lock()


def cpu_encoder_lock(providers):
    """Return the shared encoder lock for CPU-only inference.

    ``providers`` is the ONNX Runtime provider list of the adapter; anything
    that includes a GPU/accelerator provider returns a no-op context manager so
    those setups keep their parallel preloading.
    """
    if providers and all(
        provider in _CPU_ONLY_PROVIDERS for provider in providers
    ):
        return _ENCODER_LOCK
    return contextlib.nullcontext()
