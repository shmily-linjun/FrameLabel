"""Task-local temp fixture.

pytest's ``tmp_path`` creates directories with mode 0o700 on Windows; under
the DSH workspace sandbox those directories inherit an owner-only DACL that
the test process cannot list.  These storage tests only need a disposable
workspace, so they use a normal-mode directory below ``temporary/p0``.
"""

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def dataset_tmp():
    root = (
        Path(__file__).resolve().parents[2]
        / "temporary"
        / "p0"
        / f"dataset-test-{uuid.uuid4().hex[:10]}"
    )
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
