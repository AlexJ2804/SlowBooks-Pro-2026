"""Pytest wrapper that runs the jsdom DOM tests.

Why this exists: the phase-3 hotfix shipped with no JS test runner, so
the production-blocking bug — HTML5 `required` cancelling the JS submit
handler before our inline-error code could run — slipped through every
Python test that already passed. This wrapper makes the jsdom DOM tests
part of the standard `pytest` invocation so the gap can't reopen
silently. If node or jsdom isn't installed locally, the test skips
with an actionable message rather than failing.

The DOM tests themselves live at tests/dom/test_inline_error.js. Run
them directly with:
    cd tests/dom && node --test test_inline_error.js
"""
import os
import shutil
import subprocess

import pytest

DOM_DIR = os.path.join(os.path.dirname(__file__), "dom")
DOM_TEST = os.path.join(DOM_DIR, "test_inline_error.js")
JSDOM_INSTALLED = os.path.isdir(os.path.join(DOM_DIR, "node_modules", "jsdom"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.skipif(not JSDOM_INSTALLED, reason="jsdom not installed (run: cd tests/dom && npm install)")
def test_inline_error_dom_assertions():
    """Run the jsdom test suite as a subprocess; surface its TAP output on failure."""
    result = subprocess.run(
        ["node", "--test", "test_inline_error.js"],
        cwd=DOM_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "jsdom DOM tests failed.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
