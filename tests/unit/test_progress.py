"""Unit tests for progress.py — no display required."""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# Ensure the repo root is on the path so imports work without installation.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _mock_gtk_imports():
    """Inject mock GTK modules so progress.py can be imported without a display."""
    mocks = {}
    for name in [
        "gi", "gi.repository", "gi.repository.Gdk", "gi.repository.Gio",
        "gi.repository.GLib", "gi.repository.Gtk", "gi.repository.Adw",
        "gi.repository.Pango", "gi.repository.GdkPixbuf",
        "bootc_installer.views.tour", "bootc_installer.utils.run_async",
    ]:
        mocks[name] = MagicMock()
    # gi.require_version must be a callable no-op
    mocks["gi"].require_version = MagicMock()
    return mocks


class TestFishermanArgvDirect(unittest.TestCase):
    """_fisherman_argv_direct must return an argv that shell-redirects fisherman
    stdout+stderr into the log file on the host.

    Flatpak case: bash runs on the HOST via flatpak-spawn so the redirect
    happens where fisherman runs — not through the D-Bus proxy.
    """

    @classmethod
    def setUpClass(cls):
        with patch.dict("sys.modules", _mock_gtk_imports()):
            import importlib
            import bootc_installer.views.progress as mod
            # Force a fresh load with mocked GTK in case cached without mocks
            if not hasattr(mod, "_fisherman_argv_direct"):
                importlib.reload(mod)
            cls.mod = mod

    def _fn(self, in_flatpak: bool, live_iso: bool):
        self.mod._IN_FLATPAK = in_flatpak
        self.mod._LIVE_ISO = live_iso
        return self.mod._fisherman_argv_direct

    def _script(self, argv: list) -> str:
        """Return the shell script string from an argv (element after '-c')."""
        idx = argv.index("-c")
        return argv[idx + 1]

    def test_returns_list_of_strings(self):
        fn = self._fn(False, False)
        argv = fn("/tmp/recipe.json")
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_recipe_is_last_arg(self):
        """The recipe path is always the last element (bash positional $1)."""
        fn = self._fn(False, False)
        argv = fn("/tmp/recipe.json")
        self.assertEqual(argv[-1], "/tmp/recipe.json")

    def test_flatpak_normal_runs_bash_on_host(self):
        """Flatpak: bash must run on the HOST so the log redirect works."""
        fn = self._fn(in_flatpak=True, live_iso=False)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TUNA_TEST", None)
            argv = fn("/tmp/recipe.json")
        self.assertEqual(argv[0], "flatpak-spawn")
        self.assertIn("--host", argv)
        self.assertIn("bash", argv)
        script = self._script(argv)
        self.assertIn("pkexec", script)
        self.assertNotIn("flatpak-spawn", script)
        self.assertEqual(argv[-1], "/tmp/recipe.json")

    def test_flatpak_tuna_test(self):
        """TUNA_TEST env: uses sudo with custom fisherman path on the host."""
        fn = self._fn(in_flatpak=True, live_iso=False)
        with patch.dict(os.environ, {"TUNA_TEST": "1", "TUNA_FISHERMAN_PATH": "/custom/fisherman"}):
            argv = fn("/tmp/recipe.json")
        self.assertEqual(argv[0], "flatpak-spawn")
        self.assertIn("--host", argv)
        script = self._script(argv)
        self.assertIn("sudo", script)
        self.assertIn("/custom/fisherman", script)
        self.assertNotIn("flatpak-spawn", script)
        self.assertEqual(argv[-1], "/tmp/recipe.json")

    def test_live_iso(self):
        fn = self._fn(in_flatpak=False, live_iso=True)
        argv = fn("/tmp/recipe.json")
        self.assertEqual(argv[0], "bash")
        script = self._script(argv)
        self.assertIn("sudo", script)
        self.assertIn("/usr/local/bin/fisherman", script)
        self.assertEqual(argv[-1], "/tmp/recipe.json")

    def test_native(self):
        fn = self._fn(in_flatpak=False, live_iso=False)
        argv = fn("/tmp/recipe.json")
        self.assertEqual(argv[0], "bash")
        script = self._script(argv)
        self.assertIn("pkexec", script)
        self.assertIn("/usr/local/bin/fisherman", script)
        self.assertEqual(argv[-1], "/tmp/recipe.json")

    def test_log_file_redirected_in_script(self):
        """The shell script must redirect output to the log file."""
        fn = self._fn(False, False)
        argv = fn("/tmp/recipe.json")
        script = self._script(argv)
        self.assertIn(">", script)
        self.assertIn(self.mod._FISHERMAN_LOG_PATH, script)


if __name__ == "__main__":
    unittest.main()
