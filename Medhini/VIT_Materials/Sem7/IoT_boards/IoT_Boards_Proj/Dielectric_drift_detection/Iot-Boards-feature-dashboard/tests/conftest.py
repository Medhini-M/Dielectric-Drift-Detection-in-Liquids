"""
Pytest configuration for the Phase 0 integration test suite.

Redirects config.DATABASE_PATH to a throwaway temp file BEFORE any test
module imports `app` or `database.db`, so this suite never reads from or
writes to your real data/sensor.db. pytest imports conftest.py before
collecting test files in the same directory, which is what makes this
ordering safe - by the time test_phase0_integration.py does `import app`,
config.DATABASE_PATH already points at the temp file, and database/db.py's
`from config import DATABASE_PATH` picks up the patched value.
"""

import os
import shutil
import sys
import tempfile

# repo root = parent of this tests/ directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config  # noqa: E402

_tmp_dir = tempfile.mkdtemp(prefix="phase0_test_db_")
config.DATABASE_PATH = os.path.join(_tmp_dir, "test_sensor.db")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_tmp_dir, ignore_errors=True)
