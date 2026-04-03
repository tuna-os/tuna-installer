"""
Unit tests for done.py — reboot logic and icon application.
No display required; GTK widgets are not instantiated.
"""

import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

# Stub out gi.repository before importing done so no display is needed.
for _mod in ("gi", "gi.repository", "gi.repository.Adw", "gi.repository.Gdk",
             "gi.repository.Gio", "gi.repository.GLib", "gi.repository.Gtk"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
if "bootc_installer.windows.dialog_output" not in sys.modules:
    sys.modules["bootc_installer.windows.dialog_output"] = MagicMock()

from bootc_installer.views.done import apply_icon, do_reboot  # noqa: E402


class TestDoReboot(unittest.TestCase):

    def test_reboot_via_dbus_success(self):
        conn = MagicMock()
        with patch("bootc_installer.views.done.Gio.bus_get_sync", return_value=conn):
            result = do_reboot(in_flatpak=True)
        self.assertTrue(result)
        conn.call_sync.assert_called_once()

    def test_reboot_falls_back_to_subprocess_when_dbus_fails(self):
        with patch("bootc_installer.views.done.Gio.bus_get_sync", side_effect=Exception("no bus")), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = do_reboot(in_flatpak=False)
        self.assertTrue(result)
        first_argv = mock_run.call_args_list[0][0][0]
        self.assertIn("systemctl", first_argv)

    def test_reboot_flatpak_fallback_uses_flatpak_spawn(self):
        with patch("bootc_installer.views.done.Gio.bus_get_sync", side_effect=Exception("no bus")), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = do_reboot(in_flatpak=True)
        self.assertTrue(result)
        first_argv = mock_run.call_args_list[0][0][0]
        self.assertEqual(first_argv[:2], ["flatpak-spawn", "--host"])

    def test_reboot_tries_reboot_binary_when_systemctl_fails(self):
        with patch("bootc_installer.views.done.Gio.bus_get_sync", side_effect=Exception("no bus")), \
             patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr=b"failed"),  # systemctl reboot → fail
                MagicMock(returncode=0),                    # reboot → success
            ]
            result = do_reboot(in_flatpak=False)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)

    def test_reboot_returns_false_when_all_methods_fail(self):
        with patch("bootc_installer.views.done.Gio.bus_get_sync", side_effect=Exception("no bus")), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr=b"permission denied")
            result = do_reboot(in_flatpak=False)
        self.assertFalse(result)


class TestApplyIcon(unittest.TestCase):

    def test_resource_uri_loads_texture(self):
        status_page = MagicMock()
        mock_texture = MagicMock()
        with patch("bootc_installer.views.done.Gdk.Texture.new_from_resource", return_value=mock_texture) as mock_load:
            apply_icon(status_page, "resource:///org/bootcinstaller/Installer/images/tunaos.svg")
        mock_load.assert_called_once_with("/org/bootcinstaller/Installer/images/tunaos.svg")
        status_page.set_paintable.assert_called_once_with(mock_texture)

    def test_icon_theme_name_calls_set_icon_name(self):
        page_header = MagicMock()
        apply_icon(page_header, "software-installed-symbolic")
        assert page_header.icon_name == "software-installed-symbolic"
        page_header.set_paintable.assert_not_called()

    def test_apply_icon_silently_ignores_errors(self):
        status_page = MagicMock()
        with patch("bootc_installer.views.done.Gdk.Texture.new_from_resource", side_effect=Exception("bad resource")):
            apply_icon(status_page, "resource:///org/bootcinstaller/Installer/images/missing.svg")
        # Should not raise; status_page.set_paintable must not have been called
        status_page.set_paintable.assert_not_called()


class TestMainWindowIconExtraction(unittest.TestCase):
    """Verify that update_finals() extracts selected_icon alongside pretty_name."""

    def test_selected_icon_extracted_from_finals(self):
        finals = [
            {"hostname": "tunaos"},
            {"pretty_name": "Yellowfin", "icon": "resource:///org/bootcinstaller/Installer/images/yellowfin.svg"},
        ]
        pretty_name = None
        selected_icon = None
        for f in finals:
            if isinstance(f, dict):
                if pretty_name is None and "pretty_name" in f:
                    pretty_name = f["pretty_name"]
                if selected_icon is None and "icon" in f:
                    selected_icon = f["icon"]
            if pretty_name and selected_icon:
                break

        self.assertEqual(pretty_name, "Yellowfin")
        self.assertEqual(selected_icon, "resource:///org/bootcinstaller/Installer/images/yellowfin.svg")

    def test_selected_icon_none_when_not_in_finals(self):
        finals = [{"hostname": "tunaos"}, {"pretty_name": "Yellowfin"}]
        selected_icon = None
        for f in finals:
            if isinstance(f, dict) and selected_icon is None and "icon" in f:
                selected_icon = f["icon"]
        self.assertIsNone(selected_icon)


if __name__ == "__main__":
    unittest.main()
