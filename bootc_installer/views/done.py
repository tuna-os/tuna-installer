import logging
import os
import subprocess
from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from bootc_installer.widgets.page_header import TunaPageHeader  # noqa: F401
from bootc_installer.windows.dialog_output import VanillaDialogOutput

log = logging.getLogger("Installer::Done")


def apply_icon(page_header, icon_spec):
    """Set the page header icon from a resource:// URI or an icon-theme name."""
    try:
        if icon_spec.startswith("resource://"):
            resource_path = icon_spec[len("resource://"):]
            texture = Gdk.Texture.new_from_resource(resource_path)
            page_header.set_paintable(texture)
        else:
            page_header.icon_name = icon_spec
    except Exception:
        pass  # keep the default icon on any failure


def do_reboot(in_flatpak):
    """Attempt to reboot. Returns True if a reboot command succeeded."""
    # Preferred: logind D-Bus — works correctly from inside the Flatpak
    # sandbox and handles polkit transparently.
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        conn.call_sync(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "Reboot",
            GLib.Variant("(b)", (False,)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return True
    except Exception as e:
        log.warning("logind D-Bus reboot failed: %s", e)

    # Fallback: spawn systemctl / reboot on the host.
    cmds = [["systemctl", "reboot"], ["reboot"]]
    for cmd in cmds:
        argv = (["flatpak-spawn", "--host"] + cmd) if in_flatpak else cmd
        try:
            result = subprocess.run(argv, capture_output=True)
            if result.returncode == 0:
                return True
            log.warning("%s exited %d: %s", argv, result.returncode, result.stderr.decode())
        except Exception as e:
            log.warning("%s failed: %s", argv, e)

    return False


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/done.ui")
class VanillaDone(Adw.Bin):
    __gtype_name__ = "VanillaDone"

    page_header = Gtk.Template.Child()
    btn_reboot = Gtk.Template.Child()
    btn_close = Gtk.Template.Child()
    btn_log = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__log = None
        self.__boot_id = ""
        self.delta = False

        self.btn_reboot.connect("clicked", self.__on_reboot_clicked)
        self.btn_close.connect("clicked", self.__on_close_clicked)
        self.btn_log.connect("clicked", self.__on_log_clicked)

    def set_result(self, result, terminal, boot_id=""):
        self.__terminal = terminal
        self.__boot_id = boot_id

        if result:
            pretty_name = getattr(self.__window, "pretty_name", None) \
                or self.__window.recipe.get("distro_name", "the operating system")
            self.page_header.subtitle = (
                _("Restart your device to enjoy your {} experience.").format(pretty_name)
            )
            icon_spec = getattr(self.__window, "selected_icon", None)
            if icon_spec:
                apply_icon(self.page_header, icon_spec)
        else:
            self.page_header.icon_name = "dialog-error-symbolic"
            self.page_header.title = _("Something went wrong")
            self.page_header.subtitle = _("Please contact the distribution developers.")
            self.btn_reboot.set_visible(False)
            self.btn_close.set_visible(True)

    def __on_reboot_clicked(self, button):
        in_flatpak = os.path.exists("/.flatpak-info")

        if self.__boot_id:
            # Set BootNext so the firmware boots the newly installed drive on
            # the next boot, even if the install media is still plugged in.
            try:
                if in_flatpak:
                    subprocess.run(
                        ["flatpak-spawn", "--host", "efibootmgr", "--bootnext", self.__boot_id],
                        check=True,
                    )
                else:
                    subprocess.run(["efibootmgr", "--bootnext", self.__boot_id], check=True)
            except Exception as e:
                # Non-fatal — the user can always pick the right entry in the
                # BIOS/UEFI boot menu if this fails.
                log.warning("Could not set BootNext to %s: %s", self.__boot_id, e)

        if not do_reboot(in_flatpak):
            self.__show_reboot_error()

    def __show_reboot_error(self):
        dialog = Adw.AlertDialog.new(
            _("Could not reboot"),
            _("Please reboot manually by running: systemctl reboot"),
        )
        dialog.add_response("ok", _("OK"))
        dialog.present(self)

    def __on_close_clicked(self, button):
        self.__window.close()

    def __on_log_clicked(self, button):
        dialog = VanillaDialogOutput(self.__window)
        dialog.present()


