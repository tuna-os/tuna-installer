"""conftest.py for GTK UI integration tests.

Handles GResource loading and display setup.
Must run before any GTK imports in tests.

GTK4 has no offscreen backend (that was GTK3). Tests need a real X display,
provided in CI by xvfb-run. Locally, run with:
    xvfb-run -a pytest tests/ui/
or ensure DISPLAY is set to a live X server.
"""

import os
import sys

# Suppress AT-SPI accessibility bus warnings in headless CI.
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("GTK_A11Y", "none")

# Add repo root to sys.path so bootc_installer is importable.
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")

from gi.repository import Adw, Gio  # noqa: E402

import pytest  # noqa: E402


def _find_gresource() -> str | None:
    """Search common build/install paths for the compiled .gresource bundle."""
    candidates = [
        os.environ.get("TUNA_RESOURCE", ""),
        # meson builddir locations
        os.path.join(repo_root, "build", "bootc_installer", "bootc-installer.gresource"),
        os.path.join(repo_root, "_build", "bootc_installer", "bootc-installer.gresource"),
        # Flatpak builder output (flatpak run org.flatpak.Builder)
        os.path.join(repo_root, "_build", "files", "share",
                     "org.bootcinstaller.Installer", "bootc-installer.gresource"),
        # installed path (when running inside the Flatpak)
        "/app/share/org.bootcinstaller.Installer/bootc-installer.gresource",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def pytest_configure(config):
    """Load GResource bundle and initialise Adwaita at session start.

    Adw.init() must be called before instantiating any Adw widget type
    (AdwToolbarView, AdwStatusPage, etc.).  In a normal app this is done
    by Adw.Application.do_startup(); for tests we call it directly so that
    widget templates can be built without running a GLib main loop.
    """
    path = _find_gresource()
    if path:
        res = Gio.Resource.load(path)
        res._register()
        print(f"\n[conftest] GResource loaded from {path}")
    else:
        print("\n[conftest] WARNING: bootc-installer.gresource not found — "
              "set TUNA_RESOURCE=<path> or run 'meson setup build && ninja -C build' first.")

    # Register all Adw widget types so @Gtk.Template classes that reference
    # AdwToolbarView, AdwStatusPage, etc. can be instantiated in tests.
    Adw.init()
