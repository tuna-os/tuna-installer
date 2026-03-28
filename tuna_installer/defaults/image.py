# image.py
#
# Copyright 2024 mirkobrombin muhdsalm
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

import logging
import re

from gi.repository import Adw, Gtk

logger = logging.getLogger("Installer::Image")

@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/default-image.ui")
class VanillaDefaultImage(Adw.Bin):
    __gtype_name__ = "VanillaDefaultImage"

    btn_next = Gtk.Template.Child()
    group_images = Gtk.Template.Child()
    row_custom = Gtk.Template.Child()
    image_url_entry = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        self.__selected_imgref = None
        self.__radio_group = None   # first CheckButton — others join its group

        self.__build_image_rows()

        self.row_custom.connect("notify::expanded", self.__on_custom_toggled)
        self.image_url_entry.connect("changed", self.__on_url_changed)
        self.btn_next.connect("clicked", self.__window.next)

        self.__update_btn_next()

    # ── Build TunaOS image rows ───────────────────────────────────────────────

    def __build_image_rows(self):
        images = self.__window.recipe.get("images", [])

        for img in images:
            row = Adw.ActionRow()
            row.set_title(img.get("name", img.get("id", "Unknown")))
            row.set_subtitle(img.get("description", img.get("imgref", "")))
            row.set_activatable(True)

            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            if self.__radio_group is None:
                self.__radio_group = check
            else:
                check.set_group(self.__radio_group)

            imgref = img.get("imgref", "")
            check.connect("toggled", self.__on_image_toggled, imgref)
            row.add_suffix(check)
            row.set_activatable_widget(check)

            self.group_images.add(row)

            if img.get("default", False) and self.__selected_imgref is None:
                check.set_active(True)

        # If nothing was marked default, select the first one
        if self.__selected_imgref is None and images:
            first_imgref = images[0].get("imgref", "")
            self.__selected_imgref = first_imgref
            # The first CheckButton in the radio group is already active by default

    # ── Signal handlers ───────────────────────────────────────────────────────

    def __on_image_toggled(self, check, imgref):
        if check.get_active():
            self.__selected_imgref = imgref
            # Collapse custom expander if a preset is chosen
            self.row_custom.set_expanded(False)
            logger.info(f"Image selected: {imgref}")
            self.__update_btn_next()

    def __on_custom_toggled(self, row, _param):
        if row.get_expanded():
            # Deactivate all radio buttons when custom is expanded
            self.__selected_imgref = None
            if self.__radio_group:
                self.__radio_group.set_active(False)
        self.__update_btn_next()

    def __on_url_changed(self, *args):
        url = self.image_url_entry.get_text().strip()
        valid = bool(url) and re.match(r"^.+/.+:.+$", url) is not None
        if url:
            if valid:
                self.image_url_entry.remove_css_class("error")
            else:
                self.image_url_entry.add_css_class("error")
        else:
            self.image_url_entry.remove_css_class("error")
        self.__update_btn_next()

    def __update_btn_next(self):
        if self.row_custom.get_expanded():
            url = self.image_url_entry.get_text().strip()
            ok = bool(url) and re.match(r"^.+/.+:.+$", url) is not None
        else:
            ok = self.__selected_imgref is not None
        self.btn_next.set_sensitive(ok)

    # ── Test / finals ─────────────────────────────────────────────────────────

    def test_auto_advance(self):
        # Default image is already selected; just click next
        self.btn_next.emit("clicked")

    def get_finals(self):
        if self.row_custom.get_expanded():
            return {"custom_image": self.image_url_entry.get_text().strip()}
        return {"selected_image": self.__selected_imgref}

