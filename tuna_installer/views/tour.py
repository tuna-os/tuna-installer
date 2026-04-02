# tour.py
#
# Copyright 2024 mirkobrombin
# Copyright 2024 muqtadir
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

from gettext import gettext as _

import os
from gi.repository import Adw, Gtk


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/tour.ui")
class VanillaTour(Adw.Bin):
    __gtype_name__ = "VanillaTour"

    page_header = Gtk.Template.Child()
    assets_svg = Gtk.Template.Child()

    def __init__(self, window, tour, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__tour = tour
        self.__build_ui()

    def __build_ui(self):
        self.page_header.title = self.__tour.get("title", "")
        self.page_header.subtitle = self.__tour.get("description", "")

        # Support both the recipe.json format ("resource": "/org/...") and the
        # images.json carousel format ("image": "resource:///org/..." or "/path/file").
        asset = self.__tour.get("resource") or self.__tour.get("image", "")
        if asset.startswith("resource:///"):
            # Strip the URI prefix; Gtk.Picture.set_resource expects "/org/..." style.
            self.assets_svg.set_resource(asset[len("resource://"):])
        elif asset.startswith("resource://"):
            self.assets_svg.set_resource(asset[len("resource://"):])
        elif asset.startswith("/") and os.path.exists(asset):
            self.assets_svg.set_filename(asset)
        elif asset:
            # Plain GResource path ("/org/tunaos/...") — used by recipe.json tour.
            self.assets_svg.set_resource(asset)
