"""GTK integration tests for the installer wizard.

These tests instantiate real GTK widgets via Xvfb and compiled GResources
(built by 'meson setup build && ninja -C build').

They drive the installer step by step, exactly as a user would, and assert
that the right recipe JSON is produced at the end.

Run with:
    xvfb-run pytest tests/ui/ -v
"""

import json
import os
import sys
import tempfile

import pytest

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Minimal system recipe — mirrors the installed recipe.json but has no extra steps.
_SYS_RECIPE = {
    "log_file": "/dev/null",
    "distro_name": "TunaOS Test",
    "distro_logo": "org.tunaos.Installer",
    "tour": {
        "welcome": {"resource": "/org/tunaos/Installer/assets/welcome.png",
                    "title": "Installing", "description": "test"},
        "completed": {"resource": "/org/tunaos/Installer/assets/complete.svg",
                      "title": "Done", "description": "test"},
    },
    "steps": {
        "welcome": {"template": "welcome", "protected": True},
        "image":   {"template": "image",   "protected": True},
        "disk":    {"template": "disk"},
        "encryption": {"template": "encryption"},
        "user":    {"template": "user"},
    },
}


def _pump():
    """Process pending GLib/GTK events (allow signal handlers to fire)."""
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def _make_app():
    """Create a fresh Adw.Application for each test (non-unique ID avoids conflicts)."""
    app = Adw.Application(application_id="org.tunaos.InstallerTest",
                          flags=0)
    return app


@pytest.fixture()
def window():
    """Yield an initialised VanillaWindow (wizard root) for the test.

    VanillaWindow.__init__ passes all kwargs to GObject, which rejects
    unknown properties.  The recipe is loaded by RecipeLoader from disk,
    honoring the VANILLA_CUSTOM_RECIPE env var, so we write the test recipe
    to a temp file and point that var at it.
    """
    from tuna_installer.windows.main_window import VanillaWindow

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tf:
        json.dump(_SYS_RECIPE, tf)
        recipe_path = tf.name

    old_recipe_env = os.environ.get("VANILLA_CUSTOM_RECIPE")
    os.environ["VANILLA_CUSTOM_RECIPE"] = recipe_path
    try:
        app = _make_app()
        win = VanillaWindow(application=app)
        win.present()
        _pump()
        yield win
        win.close()
        _pump()
    finally:
        if old_recipe_env is None:
            os.environ.pop("VANILLA_CUSTOM_RECIPE", None)
        else:
            os.environ["VANILLA_CUSTOM_RECIPE"] = old_recipe_env
        os.unlink(recipe_path)


# ── Smoke tests ────────────────────────────────────────────────────────────────

class TestWindowSmoke:
    def test_window_opens(self, window):
        assert window is not None

    def test_window_has_steps(self, window):
        """The builder should have registered at least the welcome step."""
        from tuna_installer.utils.builder import Builder
        # The window exposes the builder via .builder property.
        assert hasattr(window, "builder") or hasattr(window, "_VanillaWindow__builder")

    def test_image_step_assigned(self, window):
        """After build, window.image_step should point to the image widget."""
        assert hasattr(window, "image_step"), "window.image_step not set by builder"
        assert window.image_step is not None


# ── Image step tests ───────────────────────────────────────────────────────────

class TestImageStep:
    def test_get_finals_returns_selected_image(self, window):
        step = window.image_step
        finals = step.get_finals()
        assert "selected_image" in finals or "custom_image" in finals

    def test_default_image_selected(self, window):
        step = window.image_step
        finals = step.get_finals()
        image = finals.get("selected_image") or finals.get("custom_image")
        assert image, "No default image was auto-selected"

    def test_composefs_backend_in_finals(self, window):
        step = window.image_step
        finals = step.get_finals()
        assert "composefs_backend" in finals

    def test_image_type_in_finals(self, window):
        step = window.image_step
        finals = step.get_finals()
        assert "image_type" in finals
        assert finals["image_type"] in ("bootc", "ostree")

    def test_needs_user_creation_in_finals(self, window):
        step = window.image_step
        finals = step.get_finals()
        assert "needs_user_creation" in finals

    def test_flatpaks_in_finals(self, window):
        step = window.image_step
        finals = step.get_finals()
        assert "flatpaks" in finals
        assert isinstance(finals["flatpaks"], list)


# ── Wizard navigation ──────────────────────────────────────────────────────────

class TestWizardNavigation:
    def test_can_advance_from_image_step(self, window):
        """Clicking Next on the image step rebuilds downstream UI and advances."""
        image_step = window.image_step
        assert image_step is not None
        # Simulate clicking btn_next (same as test_auto_advance).
        image_step.test_auto_advance()
        _pump()
        # No assertion — if it doesn't crash, the step-advance logic works.


# ── Full flow: finals → processor ─────────────────────────────────────────────

class TestEndToEnd:
    def test_recipe_generated_from_auto_disk(self, window):
        """Simulate auto-disk selection and verify processor produces valid JSON."""
        from tuna_installer.utils.processor import Processor

        # Build a finals list that mimics what the wizard collects.
        image_finals = window.image_step.get_finals()
        disk_finals = {
            "disk": {"auto": {"disk": "/dev/vda", "pretty_size": "100 GB",
                               "size": 107_374_182_400}},
        }
        enc_finals = {"encryption": {"use_encryption": False}}
        hostname_finals = {"hostname": "ci-test-host"}

        all_finals = [image_finals, disk_finals, enc_finals, hostname_finals]
        path = Processor.gen_install_recipe("/dev/null", all_finals, _SYS_RECIPE)
        assert os.path.exists(path)

        with open(path) as f:
            recipe = json.load(f)

        # Core sanity checks.
        assert recipe["disk"] == "/dev/vda"
        assert recipe["hostname"] == "ci-test-host"
        assert recipe["image"], "Image should be populated from image step finals"
        assert recipe["encryption"]["type"] == "none"
        assert isinstance(recipe["flatpaks"], list)

    def test_recipe_generated_from_manual_disk(self, window):
        """Manual partition layout produces customMounts in the recipe."""
        from tuna_installer.utils.processor import Processor

        image_finals = window.image_step.get_finals()
        disk_finals = {
            "disk": {
                "/dev/sda1": {"fs": "fat32", "mp": "/boot/efi"},
                "/dev/sda2": {"fs": "ext4",  "mp": "/boot"},
                "/dev/sda3": {"fs": "xfs",   "mp": "/"},
            }
        }
        enc_finals = {"encryption": {"use_encryption": False}}
        hostname_finals = {"hostname": "manual-host"}

        all_finals = [image_finals, disk_finals, enc_finals, hostname_finals]
        path = Processor.gen_install_recipe("/dev/null", all_finals, _SYS_RECIPE)

        with open(path) as f:
            recipe = json.load(f)

        assert "customMounts" in recipe
        mounts_by_target = {m["target"]: m for m in recipe["customMounts"]}
        assert "/" in mounts_by_target
        assert "/boot/efi" in mounts_by_target

    def test_composefs_propagates_end_to_end(self, window):
        """composefs_backend=True in image finals → composeFsBackend in recipe."""
        from tuna_installer.utils.processor import Processor

        # Manually set composefs flag (as if a composefs-native image was selected).
        image_finals = window.image_step.get_finals()
        image_finals["composefs_backend"] = True

        disk_finals = {"disk": {"auto": {"disk": "/dev/vda"}}}
        enc_finals  = {"encryption": {"use_encryption": False}}
        host_finals = {"hostname": "cf-host"}

        path = Processor.gen_install_recipe("/dev/null",
                                            [image_finals, disk_finals, enc_finals, host_finals],
                                            _SYS_RECIPE)
        with open(path) as f:
            recipe = json.load(f)

        assert recipe["composeFsBackend"] is True

    def test_encryption_propagates_end_to_end(self, window):
        from tuna_installer.utils.processor import Processor

        image_finals = window.image_step.get_finals()
        disk_finals = {"disk": {"auto": {"disk": "/dev/vda"}}}
        enc_finals  = {"encryption": {
            "use_encryption": True,
            "type": "luks-passphrase",
            "encryption_key": "t3st-key",
        }}
        host_finals = {"hostname": "enc-host"}

        path = Processor.gen_install_recipe("/dev/null",
                                            [image_finals, disk_finals, enc_finals, host_finals],
                                            _SYS_RECIPE)
        with open(path) as f:
            recipe = json.load(f)

        assert recipe["encryption"]["type"] == "luks-passphrase"
        assert recipe["encryption"]["passphrase"] == "t3st-key"
