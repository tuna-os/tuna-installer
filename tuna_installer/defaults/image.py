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

import json
import logging
import re

from gi.repository import Adw, Gio, Gtk

logger = logging.getLogger("Installer::Image")


# ── Load image catalog from bundled JSON ──────────────────────────────────────
# The manifest lives in data/images.json and is bundled as a GResource.
# Structure: {"default_image", "fallback_flatpaks", "images": [recursive tree]}
# Each node is a group {"name", "children", ...} or leaf {"name", "imgref", ...}.
# Leaves and groups may carry a "flatpaks" list; leaves inherit from ancestors.

def _load_manifest():
    try:
        data = Gio.resources_lookup_data(
            "/org/tunaos/Installer/data/images.json",
            Gio.ResourceLookupFlags.NONE,
        )
        return json.loads(data.get_data().decode())
    except Exception:
        logger.warning("Could not load images.json from GResource, trying filesystem")

    # Fallback for development: load from repo data/ directory.
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "images.json"
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.error(f"Failed to load image manifest: {e}")
        return {"default_image": "", "fallback_flatpaks": [], "images": []}


_MANIFEST = _load_manifest()
_IMAGE_TREE = _MANIFEST["images"]
_DEFAULT_IMAGE = _MANIFEST["default_image"]
_FALLBACK_FLATPAKS = _MANIFEST["fallback_flatpaks"]


# ── Widget ────────────────────────────────────────────────────────────────────

@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/default-image.ui")
class VanillaDefaultImage(Adw.Bin):
    __gtype_name__ = "VanillaDefaultImage"

    btn_next        = Gtk.Template.Child()
    search_entry    = Gtk.Template.Child()
    list_images     = Gtk.Template.Child()
    list_custom     = Gtk.Template.Child()
    row_custom      = Gtk.Template.Child()
    image_url_entry = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        self.__selected_imgref = _DEFAULT_IMAGE
        self.__selected_flatpaks = None  # per-image flatpak list (None = use fallback)
        self.__all_expanders = []   # every ExpanderRow widget
        self.__leaf_rows = []       # [(row, check, imgref, flatpaks, search_str, [ancestor_exps])]

        # Hidden anchor for the radio CheckButton group.
        self.__radio_anchor = Gtk.CheckButton()

        self.list_images.set_selection_mode(Gtk.SelectionMode.NONE)
        self.__build_list()

        self.search_entry.connect("search-changed", self.__on_search_changed)
        self.row_custom.connect("notify::expanded", self.__on_custom_toggled)
        self.image_url_entry.connect("changed", self.__on_url_changed)
        self.btn_next.connect("clicked", self.__window.next)

        self.__select_default()
        self.__update_btn_next()

    # ── Recursive tree construction ───────────────────────────────────────────

    def __build_list(self):
        for node in _IMAGE_TREE:
            self.__build_node(self.list_images, node, [], "")

        # Recipe-defined extra images (flat group).
        extra = self.__window.recipe.get("images", [])
        if extra:
            exp = Adw.ExpanderRow(title="Recipe Images")
            self.__all_expanders.append(exp)
            for img in extra:
                imgref = img.get("imgref", "")
                if not imgref:
                    continue
                self.__add_leaf(
                    exp, img.get("name", imgref), imgref,
                    img.get("description", ""), "", [exp])
            self.list_images.append(exp)

    def __build_node(self, parent, node, ancestors, search_ctx, flatpaks_ctx=None):
        """Recursively build ExpanderRow groups and ActionRow leaves."""
        # Inherit flatpaks from nearest ancestor that defines them.
        node_flatpaks = node.get("flatpaks", flatpaks_ctx)
        if "imgref" in node:
            self.__add_leaf(parent, node["name"], node["imgref"],
                            node.get("desc", ""), search_ctx, ancestors,
                            node_flatpaks)
            return

        exp = Adw.ExpanderRow(title=node["name"])
        if "subtitle" in node:
            exp.set_subtitle(node["subtitle"])
        self.__all_expanders.append(exp)

        child_ctx = search_ctx + " " + node["name"]
        if "search_extra" in node:
            child_ctx += " " + node["search_extra"]
        child_ancestors = ancestors + [exp]

        for child in node.get("children", []):
            self.__build_node(exp, child, child_ancestors, child_ctx, node_flatpaks)

        if parent is self.list_images:
            parent.append(exp)
        else:
            parent.add_row(exp)

    def __add_leaf(self, parent, name, imgref, desc, search_ctx, ancestors,
                   flatpaks=None):
        search_str = f"{search_ctx} {name} {desc} {imgref}".lower()

        row = Adw.ActionRow(title=name, subtitle=imgref)
        if desc:
            row.set_tooltip_text(desc)
        row.set_activatable(True)

        check = Gtk.CheckButton()
        check.set_group(self.__radio_anchor)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        check.connect("toggled", self.__on_check_toggled, imgref, flatpaks)

        parent.add_row(row)
        self.__leaf_rows.append((row, check, imgref, flatpaks, search_str, list(ancestors)))

    def __select_default(self):
        for _row, check, imgref, _flatpaks, _search, ancestors in self.__leaf_rows:
            if imgref == _DEFAULT_IMAGE:
                check.set_active(True)
                for exp in ancestors:
                    exp.set_expanded(True)
                return
        if self.__leaf_rows:
            self.__leaf_rows[0][1].set_active(True)

    # ── Selection handlers ────────────────────────────────────────────────────

    def __on_check_toggled(self, check, imgref, flatpaks):
        if check.get_active():
            self.__selected_imgref = imgref
            self.__selected_flatpaks = flatpaks
            logger.info(f"Image selected: {imgref}")
            if self.row_custom.get_expanded():
                self.row_custom.set_expanded(False)
            self.__update_btn_next()

    def __on_custom_toggled(self, expander, _param):
        if expander.get_expanded():
            self.__radio_anchor.set_active(True)
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

    # ── Search / filtering ────────────────────────────────────────────────────

    def __on_search_changed(self, entry):
        query = entry.get_text().lower().strip()

        if not query:
            for exp in self.__all_expanders:
                exp.set_visible(True)
                exp.set_expanded(False)
            for row, _, _, _, _, _ in self.__leaf_rows:
                row.set_visible(True)
            self.__expand_default_path()
            return

        # Determine which leaves match and which expanders are needed.
        visible_expanders = set()
        for row, _, _, _flatpaks, search_str, ancestors in self.__leaf_rows:
            if query in search_str:
                row.set_visible(True)
                for exp in ancestors:
                    visible_expanders.add(id(exp))
            else:
                row.set_visible(False)

        for exp in self.__all_expanders:
            if id(exp) in visible_expanders:
                exp.set_visible(True)
                exp.set_expanded(True)
            else:
                exp.set_visible(False)

    def __expand_default_path(self):
        for _, _, imgref, _, _, ancestors in self.__leaf_rows:
            if imgref == _DEFAULT_IMAGE:
                for exp in ancestors:
                    exp.set_expanded(True)
                return
        if self.__all_expanders:
            self.__all_expanders[0].set_expanded(True)

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
        flatpaks = self.__selected_flatpaks or _FALLBACK_FLATPAKS
        if self.row_custom.get_expanded():
            return {
                "custom_image": self.image_url_entry.get_text().strip(),
                "flatpaks": _FALLBACK_FLATPAKS,
            }
        return {
            "selected_image": self.__selected_imgref,
            "flatpaks": flatpaks,
        }

