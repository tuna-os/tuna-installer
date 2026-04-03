# encryption.py
#
# Copyright 2024 mirkobrombin
#
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

from gi.repository import Adw, GLib, Gtk
import os

@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-encryption.ui")
class VanillaDefaultEncryption(Adw.Bin):
    __gtype_name__ = "VanillaDefaultEncryption"

    btn_next = Gtk.Template.Child()
    page_header = Gtk.Template.Child()

    use_encryption_switch = Gtk.Template.Child()
    tpm2_switch = Gtk.Template.Child()

    encryption_pass_entry = Gtk.Template.Child()
    encryption_pass_entry_confirm = Gtk.Template.Child()

    password_filled = False

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        self.btn_next.connect("clicked", self.__window.next)
        self.use_encryption_switch.connect(
            "state-set", self.__on_encryption_switch_set)
        self.tpm2_switch.connect("state-set", self.__on_tpm2_switch_set)
        self.encryption_pass_entry.connect(
            "changed", self.__on_password_changed)
        self.encryption_pass_entry_confirm.connect(
            "changed", self.__on_password_changed
        )

        self.__update_btn_next()

    def test_auto_advance(self):
        # Ensure encryption is off — TPM2 won't work on virtual/loop disks
        self.use_encryption_switch.set_active(False)
        self.tpm2_switch.set_active(False)
        self.btn_next.emit("clicked")

    def get_finals(self):
        use_enc = self.use_encryption_switch.get_active()
        if not use_enc:
            return {"encryption": {"use_encryption": False, "encryption_key": ""}}
        passphrase = self.encryption_pass_entry.get_text()
        enc_type = "tpm2-luks-passphrase" if self.tpm2_switch.get_active() else "luks-passphrase"
        return {
            "encryption": {
                "use_encryption": True,
                "type": enc_type,
                "encryption_key": passphrase,
            }
        }

    def __on_encryption_switch_set(self, state, user_data):
        if self.use_encryption_switch.get_active():
            self.page_header.icon_name = "changes-prevent-symbolic"
        else:
            self.page_header.icon_name = "changes-allow-symbolic"
            self.tpm2_switch.set_active(False)

        self.__update_btn_next()

    def __on_tpm2_switch_set(self, state, user_data):
        self.__update_btn_next()

    def __on_password_changed(self, *args):
        password = self.encryption_pass_entry.get_text()
        if (
            password == self.encryption_pass_entry_confirm.get_text()
            and password.strip()
        ):
            self.password_filled = True
            self.encryption_pass_entry_confirm.remove_css_class("error")
        else:
            self.password_filled = False
            self.encryption_pass_entry_confirm.add_css_class("error")

        self.__update_btn_next()

    def __update_btn_next(self):
        use_enc = self.use_encryption_switch.get_active()
        rule = not use_enc or self.password_filled
        self.btn_next.set_sensitive(rule)
