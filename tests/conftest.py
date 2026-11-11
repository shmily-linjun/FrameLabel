"""Keep disposable pytest files inside the repository's temporary directory."""

import os
from pathlib import Path
import tempfile
import uuid


def pytest_configure(config):
    """Create an isolated temporary directory for each pytest process."""
    temporary_root = Path(__file__).resolve().parents[1] / "temporary"
    run_directory = (
        temporary_root
        / "runs"
        / f"pytest-{os.getpid()}-{uuid.uuid4().hex}"
    )
    process_temp = run_directory / "process"
    process_temp.mkdir(parents=True)

    # An explicitly supplied --basetemp takes precedence. Otherwise pytest
    # creates a numbered fixture directory below this per-run temporary root.
    # Do not use one fixed --basetemp: pytest deletes it before reuse.
    if config.option.basetemp is None:
        fixture_temp = run_directory / "fixtures"
        fixture_temp.mkdir()
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(fixture_temp)

    # Cover direct tempfile users and subprocesses, not just tmp_path.
    for variable in ("TEMP", "TMP", "TMPDIR"):
        os.environ[variable] = str(process_temp)
    tempfile.tempdir = str(process_temp)
