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

# ── Known TunaOS images ───────────────────────────────────────────────────────
# Each entry: (base_id, tag, display_name, description)
# Add more rows here as new images are published.

_BASES = [
    ("albacore", "Albacore"),
    ("yellowfin", "Yellowfin"),
    ("skipjack",  "Skipjack"),
    ("bonito",    "Bonito"),
]

_TAGS = [
    ("gnome",     "GNOME",                  "GNOME desktop"),
    ("gnome-hwe", "GNOME — HWE Kernel",     "GNOME with Hardware Enablement kernel"),
    ("gnome50",   "GNOME 50",               "GNOME 50 series"),
    ("gnome-gdx", "GNOME — Gaming",         "GNOME with gaming optimisations"),
    ("kde",       "KDE Plasma",             "KDE Plasma desktop"),
    ("kde-hwe",   "KDE Plasma — HWE Kernel","KDE Plasma with Hardware Enablement kernel"),
    ("kde-gdx",   "KDE Plasma — Gaming",    "KDE Plasma with gaming optimisations"),
    ("niri",      "Niri",                   "Niri scrolling Wayland compositor"),
]

_DEFAULT_IMAGE = "ghcr.io/tuna-os/yellowfin:gnome-hwe"

_REGISTRY = "ghcr.io/tuna-os"


def _build_image_catalog():
    """Return list of dicts for every base×tag combination."""
    catalog = []
    for base_id, base_name in _BASES:
        for tag_id, tag_name, tag_desc in _TAGS:
            catalog.append({
                "name":    f"{base_name}: {tag_name}",
                "imgref":  f"{_REGISTRY}/{base_id}:{tag_id}",
                "desc":    tag_desc,
                "search":  f"{base_id} {base_name} {tag_id} {tag_name} {tag_desc}".lower(),
            })
    return catalog


_IMAGE_CATALOG = _build_image_catalog()


# ── Widget ────────────────────────────────────────────────────────────────────

@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/default-image.ui")
class VanillaDefaultImage(Adw.Bin):
    __gtype_name__ = "VanillaDefaultImage"

    btn_next       = Gtk.Template.Child()
    search_entry   = Gtk.Template.Child()
    list_images    = Gtk.Template.Child()
    list_custom    = Gtk.Template.Child()
    row_custom     = Gtk.Template.Child()
    image_url_entry = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        self.__selected_imgref = _DEFAULT_IMAGE
        self.__rows = []   # list of (Gtk.ListBoxRow, imgref, search_str)

        self.__build_list()

        self.search_entry.connect("search-changed", self.__on_search_changed)
        self.list_images.connect("row-selected", self.__on_row_selected)
        self.row_custom.connect("notify::expanded", self.__on_custom_toggled)
        self.image_url_entry.connect("changed", self.__on_url_changed)
        self.btn_next.connect("clicked", self.__window.next)

        self.__select_default()
        self.__update_btn_next()

    # ── List construction ─────────────────────────────────────────────────────

    def __build_list(self):
        # Allow extra images defined in the recipe (for future extensibility)
        extra = self.__window.recipe.get("images", [])
        catalog = list(_IMAGE_CATALOG)
        for img in extra:
            imgref = img.get("imgref", "")
            if imgref and not any(r[1] == imgref for r in self.__rows):
                name = img.get("name", imgref)
                desc = img.get("description", "")
                catalog.append({
                    "name":   name,
                    "imgref": imgref,
                    "desc":   desc,
                    "search": f"{name} {imgref} {desc}".lower(),
                })

        for entry in catalog:
            row = self.__make_row(entry)
            self.list_images.append(row)
            self.__rows.append((row, entry["imgref"], entry["search"]))

        self.list_images.set_filter_func(self.__filter_func)

    def __make_row(self, entry):
        row = Adw.ActionRow()
        row.set_title(entry["name"])
        row.set_subtitle(entry["imgref"])
        if entry.get("desc"):
            row.set_tooltip_text(entry["desc"])
        row.set_activatable(True)
        return row

    def __select_default(self):
        for row, imgref, _ in self.__rows:
            if imgref == _DEFAULT_IMAGE:
                self.list_images.select_row(row)
                return
        # Fall back to first row
        if self.__rows:
            self.list_images.select_row(self.__rows[0][0])

    # ── Filtering ─────────────────────────────────────────────────────────────

    def __filter_func(self, row):
        query = self.search_entry.get_text().lower().strip()
        if not query:
            return True
        for list_row, imgref, search_str in self.__rows:
            if list_row is row:
                return query in search_str
        return True

    def __on_search_changed(self, entry):
        self.list_images.invalidate_filter()
        # Re-select first visible row if current selection is now hidden
        selected = self.list_images.get_selected_row()
        if selected is None or not selected.get_visible():
            self.__select_first_visible()

    def __select_first_visible(self):
        row = self.list_images.get_row_at_index(0)
        idx = 0
        while row is not None:
            if row.get_visible():
                self.list_images.select_row(row)
                return
            idx += 1
            row = self.list_images.get_row_at_index(idx)
        self.list_images.unselect_all()
        self.__selected_imgref = None
        self.__update_btn_next()

    # ── Selection handlers ────────────────────────────────────────────────────

    def __on_row_selected(self, listbox, row):
        if row is None:
            self.__selected_imgref = None
        else:
            for list_row, imgref, _ in self.__rows:
                if list_row is row:
                    self.__selected_imgref = imgref
                    logger.info(f"Image selected: {imgref}")
                    break
        self.__update_btn_next()

    def __on_custom_toggled(self, expander, _param):
        if expander.get_expanded():
            self.list_images.unselect_all()
            self.__selected_imgref = None
        self.__update_btn_next()

    def __on_url_changed(self, entry):
        url = entry.get_text().strip()
        valid = bool(url) and re.match(r"^.+/.+:.+$", url) is not None
        if url:
            entry.remove_css_class("error") if valid else entry.add_css_class("error")
        else:
            entry.remove_css_class("error")
        self.__update_btn_next()

    # ── Sensitivity ───────────────────────────────────────────────────────────

    def __update_btn_next(self):
        if self.row_custom.get_expanded():
            url = self.image_url_entry.get_text().strip()
            ok = bool(url) and re.match(r"^.+/.+:.+$", url) is not None
        else:
            ok = self.__selected_imgref is not None
        self.btn_next.set_sensitive(ok)

    # ── Test / finals ─────────────────────────────────────────────────────────

    def test_auto_advance(self):
        self.btn_next.emit("clicked")

    def get_finals(self):
        if self.row_custom.get_expanded():
            return {"custom_image": self.image_url_entry.get_text().strip()}
        return {"selected_image": self.__selected_imgref}

