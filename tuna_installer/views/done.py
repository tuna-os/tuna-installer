# done.py
#
# Copyright 2024 mirkobrombin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import subprocess
from gettext import gettext as _

from gi.repository import Adw, Gtk

from tuna_installer.windows.dialog_output import VanillaDialogOutput


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/done.ui")
class VanillaDone(Adw.Bin):
    __gtype_name__ = "VanillaDone"

    status_page = Gtk.Template.Child()
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
            self.status_page.set_description(
                _("Restart your device to enjoy your {} experience.").format(pretty_name)
            )
        else:
            self.status_page.set_icon_name("dialog-error-symbolic")
            self.status_page.set_title(_("Something went wrong"))
            self.status_page.set_description(
                _("Please contact the distribution developers.")
            )
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
                import logging
                logging.getLogger("Installer::Done").warning(
                    "Could not set BootNext to %s: %s", self.__boot_id, e
                )
        if in_flatpak:
            subprocess.run(["flatpak-spawn", "--host", "systemctl", "reboot"])
        else:
            subprocess.run(["systemctl", "reboot"])

    def __on_close_clicked(self, button):
        self.__window.close()

    def __on_log_clicked(self, button):
        dialog = VanillaDialogOutput(self.__window)
        dialog.present()
