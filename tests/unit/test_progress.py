"""Unit tests for progress.py — no display required."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the repo root is on the path so imports work without installation.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestFishermanArgvDirect(unittest.TestCase):
    """Test _fisherman_argv_direct for each execution environment."""

    def _import(self, in_flatpak: bool, live_iso: bool):
        """Re-import the function with patched module-level constants."""
        import importlib
        import tuna_installer.views.progress as mod

        orig_flatpak = mod._IN_FLATPAK
        orig_iso = mod._LIVE_ISO
        mod._IN_FLATPAK = in_flatpak
        mod._LIVE_ISO = live_iso
        try:
            return mod._fisherman_argv_direct
        finally:
            mod._IN_FLATPAK = orig_flatpak
            mod._LIVE_ISO = orig_iso

    def test_flatpak_normal(self):
        fn = self._import(in_flatpak=True, live_iso=False)
        import tuna_installer.views.progress as mod
        mod._IN_FLATPAK = True
        mod._LIVE_ISO = False
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TUNA_TEST", None)
            argv = fn("/tmp/recipe.json")
        self.assertEqual(argv[0], "flatpak-spawn")
        self.assertIn("pkexec", argv)
        self.assertIn("/tmp/recipe.json", argv)

    def test_flatpak_tuna_test(self):
        import tuna_installer.views.progress as mod
        mod._IN_FLATPAK = True
        mod._LIVE_ISO = False
        with patch.dict(os.environ, {"TUNA_TEST": "1", "TUNA_FISHERMAN_PATH": "/custom/fisherman"}):
            argv = mod._fisherman_argv_direct("/tmp/recipe.json")
        self.assertEqual(argv[0], "flatpak-spawn")
        self.assertIn("sudo", argv)
        self.assertIn("/custom/fisherman", argv)
        self.assertIn("/tmp/recipe.json", argv)

    def test_live_iso(self):
        import tuna_installer.views.progress as mod
        mod._IN_FLATPAK = False
        mod._LIVE_ISO = True
        argv = mod._fisherman_argv_direct("/tmp/recipe.json")
        self.assertEqual(argv[0], "sudo")
        self.assertIn("/usr/local/bin/fisherman", argv)
        self.assertIn("/tmp/recipe.json", argv)

    def test_native(self):
        import tuna_installer.views.progress as mod
        mod._IN_FLATPAK = False
        mod._LIVE_ISO = False
        argv = mod._fisherman_argv_direct("/tmp/recipe.json")
        self.assertEqual(argv[0], "pkexec")
        self.assertIn("/usr/local/bin/fisherman", argv)
        self.assertIn("/tmp/recipe.json", argv)

    def test_returns_list(self):
        import tuna_installer.views.progress as mod
        argv = mod._fisherman_argv_direct("/some/recipe.json")
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv))


if __name__ == "__main__":
    unittest.main()
