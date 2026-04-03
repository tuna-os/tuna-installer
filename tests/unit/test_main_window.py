"""Regression tests for main_window.py navigation — no display required.

Covers the carousel navigation helpers (next/back) to ensure they
handle pages that lack a ``delta`` attribute gracefully.

Regression test for:
  AttributeError: 'VanillaProgress' object has no attribute 'delta'
  which prevented start() from ever being called, causing blank logs.
"""
import ast
import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_MAIN_WINDOW_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "bootc_installer", "windows", "main_window.py"
)


class TestDeltaAccessSafety(unittest.TestCase):
    """Verify that next() and back() use getattr for page.delta access.

    Direct attribute access (page.delta) crashes on pages like VanillaProgress
    that don't define a delta attribute. The fix is getattr(page, 'delta', False).
    """

    def test_no_bare_page_dot_delta_in_next_or_back(self):
        """Source code must not use 'page.delta' — must use getattr()."""
        with open(_MAIN_WINDOW_PATH) as f:
            source = f.read()

        tree = ast.parse(source)

        bare_accesses = []
        for node in ast.walk(tree):
            # Look for `page.delta` attribute access (not inside getattr)
            if isinstance(node, ast.Attribute) and node.attr == "delta":
                if isinstance(node.value, ast.Name) and node.value.id == "page":
                    # Check parent — if it's inside a getattr call, that's fine
                    bare_accesses.append(node.lineno)

        # getattr(page, "delta", False) produces an ast.Call with ast.Name("getattr"),
        # not an ast.Attribute node, so any ast.Attribute for page.delta is bare.
        self.assertEqual(
            bare_accesses, [],
            f"Found bare page.delta access at lines {bare_accesses}. "
            f"Use getattr(page, 'delta', False) instead to avoid AttributeError "
            f"on pages like VanillaProgress that don't define delta."
        )

    def test_getattr_pattern_works_without_delta(self):
        """getattr fallback returns False for objects without delta."""
        class NoDeltaPage:
            pass
        page = NoDeltaPage()
        self.assertFalse(getattr(page, "delta", False))

    def test_getattr_pattern_works_with_delta_true(self):
        """getattr returns the actual value when delta exists."""
        class DeltaPage:
            delta = True
        page = DeltaPage()
        self.assertTrue(getattr(page, "delta", False))

    def test_getattr_pattern_works_with_delta_false(self):
        """getattr returns False when delta exists but is False."""
        class DeltaPage:
            delta = False
        page = DeltaPage()
        self.assertFalse(getattr(page, "delta", False))


if __name__ == "__main__":
    unittest.main()
