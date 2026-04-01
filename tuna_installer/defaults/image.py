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
import os
import re
import urllib.request
import urllib.error

from gi.repository import Adw, Gio, Gtk

logger = logging.getLogger("Installer::Image")


# ── Load image catalog from bundled JSON ──────────────────────────────────────
# The manifest lives in data/images.json and is bundled as a GResource.
# Structure: {"default_image", "fallback_flatpaks", "images": [recursive tree]}
# Each node is a group {"name", "children", ...} or leaf {"name", "imgref", ...}.
# Leaves and groups may carry a "flatpaks" list; leaves inherit from ancestors.
#
# Distros can ship a custom image catalog by placing their own images.json at:
#   /etc/tuna-installer/images.json          (system-wide override)
#   $XDG_CONFIG_HOME/tuna-installer/images.json  (per-user override, dev/testing)
# The first file found takes priority over the bundled GResource default.

def _load_manifest():
    import pathlib

    # 1. Per-user override (useful for testing custom catalogs without root).
    xdg_config = pathlib.Path(
        os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")
    )
    user_override = xdg_config / "tuna-installer" / "images.json"
    if user_override.exists():
        try:
            manifest = json.loads(user_override.read_text())
            logger.info(f"Loaded image manifest from user override: {user_override}")
            return manifest
        except Exception as e:
            logger.warning(f"Failed to parse user override {user_override}: {e}")

    # 2. System-wide override (distros drop their catalog here).
    system_override = pathlib.Path("/etc/tuna-installer/images.json")
    if system_override.exists():
        try:
            manifest = json.loads(system_override.read_text())
            logger.info(f"Loaded image manifest from system override: {system_override}")
            return manifest
        except Exception as e:
            logger.warning(f"Failed to parse system override {system_override}: {e}")

    # 3. Bundled GResource (default shipped with the installer).
    try:
        data = Gio.resources_lookup_data(
            "/org/tunaos/Installer/images.json",
            Gio.ResourceLookupFlags.NONE,
        )
        logger.debug("Loaded image manifest from GResource")
        return json.loads(data.get_data().decode())
    except Exception:
        logger.warning("Could not load images.json from GResource, trying filesystem")

    # 4. Installed data path (flatpak: /app/share/tuna-installer/images.json).
    for installed in [
        pathlib.Path("/app/share/tuna-installer/images.json"),
        pathlib.Path("/usr/share/tuna-installer/images.json"),
    ]:
        try:
            manifest = json.loads(installed.read_text())
            logger.info(f"Loaded image manifest from installed path: {installed}")
            return manifest
        except Exception:
            pass

    # 5. Filesystem fallback for development (run from repo root).
    dev_path = pathlib.Path(__file__).resolve().parent.parent.parent / "fisherman" / "data" / "images.json"
    try:
        manifest = json.loads(dev_path.read_text())
        logger.info(f"Loaded image manifest from dev path: {dev_path}")
        return manifest
    except Exception as e:
        logger.error(f"Failed to load image manifest from all sources: {e}")
        return {"default_image": "", "fallback_flatpaks": [], "images": []}


_MANIFEST = _load_manifest()
_IMAGE_TREE = _MANIFEST["images"]
_DEFAULT_IMAGE = _MANIFEST["default_image"]
_FALLBACK_FLATPAKS = _MANIFEST["fallback_flatpaks"]
_APP_NAME = _MANIFEST.get("app_name", "TunaOS Installer")


# ── Pretty name helpers ───────────────────────────────────────────────────────

def _imgref_to_pretty_name(imgref: str) -> str:
    """Derive a human-readable name from an OCI image reference.

    'ghcr.io/ublue-os/bluefin-dx:latest' → 'Bluefin DX'
    First word: Title Case. Subsequent words: ALL CAPS.
    """
    try:
        slug = imgref.split("/")[-1].split(":")[0]   # e.g. "bluefin-dx"
        parts = slug.replace("_", "-").split("-")
        return " ".join(
            p.capitalize() if i == 0 else p.upper()
            for i, p in enumerate(parts)
        )
    except Exception:
        return imgref


def _count_leaves(nodes: list) -> int:
    """Recursively count selectable leaf image nodes in the tree."""
    count = 0
    for node in nodes:
        if "imgref" in node:
            count += 1
        else:
            count += _count_leaves(node.get("children", []))
    return count


_LEAF_COUNT = _count_leaves(_IMAGE_TREE)


def _fetch_remote_flatpak_list(url: str) -> list[str] | None:
    """Fetch a remote flatpak list and return app IDs.

    Handles two formats:
    - Brewfile:  ``flatpak "com.example.App"`` lines
    - Plain ref: ``app/com.example.App/x86_64/stable`` lines (one per line)
    - Plain IDs: ``com.example.App`` lines (one per line, no slash)

    Returns None on network/parse error so the caller can fall back gracefully.
    Only app entries are included; runtime entries are excluded.
    """
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            text = resp.read().decode("utf-8")
        apps = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Brewfile format: flatpak "com.example.App"
            m = re.match(r'^flatpak\s+"([^"]+)"', line)
            if m:
                apps.append(m.group(1))
                continue
            # Plain ref format: app/com.example.App/x86_64/stable
            if line.startswith("app/"):
                parts = line.split("/")
                if len(parts) >= 2:
                    apps.append(parts[1])
                continue
            # Plain app ID: com.example.App (must look like a reverse-DNS ID)
            if re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*(\.[a-zA-Z][a-zA-Z0-9_-]*){1,}$', line):
                apps.append(line)
        logger.info(f"Fetched {len(apps)} flatpaks from {url}")
        return apps if apps else None
    except Exception as e:
        logger.warning(f"Could not fetch flatpaks from {url}: {e}")
        return None


def _make_icon(icon_spec: str, size: int = 32) -> "Gtk.Image | None":
    """Return a GtkImage for an icon spec, or None if blank/unresolvable.

    Supported formats:
      resource:///org/tunaos/Installer/images/foo.svg  — bundled GResource
      /absolute/path/to/icon.svg                       — filesystem (distro override)
      icon-name-symbolic                               — XDG icon theme name
    """
    if not icon_spec:
        return None
    img = Gtk.Image()
    img.set_pixel_size(size)
    try:
        if icon_spec.startswith("resource://"):
            img.set_from_resource(icon_spec[len("resource://"):])
        elif icon_spec.startswith("/"):
            img.set_from_file(icon_spec)
        else:
            img.set_from_icon_name(icon_spec)
        return img
    except Exception as e:
        logger.warning(f"Could not load icon {icon_spec!r}: {e}")
        return None



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
        self.__selected_carousel = None  # per-image carousel slides (None = use recipe default)
        self.__selected_needs_user_creation = False
        self.__selected_composefs_backend = False  # image requires composefs backend
        self.__selected_image_type = "bootc"        # "bootc" or "ostree"
        self.__selected_icon = None      # icon spec for selected image (str or None)
        self.__selected_pretty_name = _imgref_to_pretty_name(_DEFAULT_IMAGE)
        self.__all_expanders = []   # every ExpanderRow widget
        self.__leaf_rows = []       # [(row, check, imgref, flatpaks, icon, carousel, needs_user, composefs, image_type, search_str, [ancestor_exps])]

        # Hidden anchor for the radio CheckButton group.
        self.__radio_anchor = Gtk.CheckButton()

        self.list_images.set_selection_mode(Gtk.SelectionMode.NONE)
        self.__build_list()

        self.search_entry.connect("search-changed", self.__on_search_changed)
        self.row_custom.connect("notify::expanded", self.__on_custom_toggled)
        self.image_url_entry.connect("changed", self.__on_url_changed)
        self.btn_next.connect("clicked", self.__on_next_clicked)

        self.__select_default()
        self.__update_btn_next()

    def __on_next_clicked(self, *args):
        # Rebuild downstream steps so they can react to the selected image
        # (e.g. show/hide user-creation step based on needs_user_creation).
        self.__window.rebuild_ui_after_image()
        self.__window.next()

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

    def __build_node(self, parent, node, ancestors, search_ctx, flatpaks_ctx=None, icon_ctx=None, carousel_ctx=None, needs_user_ctx=False, composefs_ctx=False, image_type_ctx="bootc"):
        """Recursively build ExpanderRow groups and ActionRow leaves."""
        # Inherit flatpaks, icon, carousel, needs_user_creation, composefs, and image_type from nearest ancestor.
        node_flatpaks = node.get("flatpaks", flatpaks_ctx)
        node_icon = node.get("icon", icon_ctx)
        node_carousel = node.get("carousel", carousel_ctx)
        node_needs_user = node.get("needs_user_creation", needs_user_ctx)
        node_composefs = node.get("composefs", composefs_ctx)
        node_image_type = node.get("image_type", image_type_ctx)

        if "imgref" in node:
            self.__add_leaf(parent, node["name"], node["imgref"],
                            node.get("desc", ""), search_ctx, ancestors,
                            node_flatpaks, node_icon, node_carousel, node_needs_user,
                            node_composefs, node_image_type)
            return

        exp = Adw.ExpanderRow(title=node["name"])
        if "subtitle" in node:
            exp.set_subtitle(node["subtitle"])

        icon_spec = node.get("icon")
        if icon_spec:
            img = _make_icon(icon_spec, size=32)
            if img:
                img.add_css_class("icon-dropshadow")
                exp.add_prefix(img)

        self.__all_expanders.append(exp)

        child_ctx = search_ctx + " " + node["name"]
        if "search_extra" in node:
            child_ctx += " " + node["search_extra"]
        child_ancestors = ancestors + [exp]

        for child in node.get("children", []):
            self.__build_node(exp, child, child_ancestors, child_ctx, node_flatpaks, node_icon, node_carousel, node_needs_user, node_composefs, node_image_type)

        if parent is self.list_images:
            parent.append(exp)
        else:
            parent.add_row(exp)

    def __add_leaf(self, parent, name, imgref, desc, search_ctx, ancestors,
                   flatpaks=None, icon=None, carousel=None, needs_user=False,
                   composefs=False, image_type="bootc"):
        search_str = f"{search_ctx} {name} {desc} {imgref}".lower()

        row = Adw.ActionRow(title=name, subtitle=imgref)
        if desc:
            row.set_tooltip_text(desc)
        row.set_activatable(True)

        check = Gtk.CheckButton()
        check.set_group(self.__radio_anchor)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        check.connect("toggled", self.__on_check_toggled, imgref, flatpaks, icon, carousel, needs_user, composefs, image_type)

        # Leaf icon — only for nodes that explicitly define one (e.g. TunaOS variants).
        if icon:
            img = _make_icon(icon, size=24)
            if img:
                row.add_suffix(img)

        parent.add_row(row)
        self.__leaf_rows.append((row, check, imgref, flatpaks, icon, carousel, needs_user, composefs, image_type, search_str, list(ancestors)))

    def __select_default(self):
        for _row, check, imgref, _flatpaks, _icon, _carousel, _needs_user, _composefs, _image_type, _search, ancestors in self.__leaf_rows:
            if imgref == _DEFAULT_IMAGE:
                check.set_active(True)
                for exp in ancestors:
                    exp.set_expanded(True)
                return
        if self.__leaf_rows:
            self.__leaf_rows[0][1].set_active(True)

    # ── Selection handlers ────────────────────────────────────────────────────

    def __on_check_toggled(self, check, imgref, flatpaks, icon, carousel, needs_user, composefs, image_type):
        if check.get_active():
            self.__selected_imgref = imgref
            self.__selected_icon = icon
            self.__selected_carousel = carousel
            self.__selected_needs_user_creation = needs_user
            self.__selected_composefs_backend = composefs
            self.__selected_image_type = image_type
            self.__selected_pretty_name = _imgref_to_pretty_name(imgref)
            # flatpaks may be a list of app IDs or a URL string pointing to a remote list.
            if isinstance(flatpaks, str) and flatpaks.startswith("http"):
                self.__selected_flatpaks = _fetch_remote_flatpak_list(flatpaks)
            else:
                self.__selected_flatpaks = flatpaks
            logger.info(f"Image selected: {imgref} ({self.__selected_pretty_name})")
            if self.row_custom.get_expanded():
                self.row_custom.set_expanded(False)
            self.__update_btn_next()

    def __on_custom_toggled(self, expander, _param):
        if expander.get_expanded():
            self.__radio_anchor.set_active(True)
            self.__selected_imgref = None
            self.__selected_icon = None
            self.__selected_carousel = None
            self.__selected_needs_user_creation = False
            self.__selected_composefs_backend = False
            self.__selected_image_type = "bootc"
            self.__selected_pretty_name = None
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
            for row, _, _, _, _, _, _, _, _, _, _ in self.__leaf_rows:
                row.set_visible(True)
            self.__expand_default_path()
            return

        # Determine which leaves match and which expanders are needed.
        visible_expanders = set()
        for row, _, _, _flatpaks, _icon, _carousel, _needs_user, _composefs, _image_type, search_str, ancestors in self.__leaf_rows:
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
        for _, _, imgref, _, _, _, _, _, ancestors in self.__leaf_rows:
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

    @property
    def skip_screen(self) -> bool:
        """True when the manifest contains only one selectable image."""
        return _LEAF_COUNT <= 1

    @property
    def selected_needs_user_creation(self) -> bool:
        """True if the selected image requires an explicit user creation step."""
        return self.__selected_needs_user_creation

    def test_auto_advance(self):
        self.btn_next.emit("clicked")

    def get_finals(self):
        flatpaks = self.__selected_flatpaks or _FALLBACK_FLATPAKS
        if self.row_custom.get_expanded():
            url = self.image_url_entry.get_text().strip()
            return {
                "custom_image": url,
                "pretty_name": _imgref_to_pretty_name(url),
                "flatpaks": _FALLBACK_FLATPAKS,
                "carousel": None,
                "needs_user_creation": False,
                "composefs_backend": False,
                "image_type": "bootc",
                "icon": None,
            }
        return {
            "selected_image": self.__selected_imgref,
            "pretty_name": self.__selected_pretty_name,
            "flatpaks": flatpaks,
            "carousel": self.__selected_carousel,
            "needs_user_creation": self.__selected_needs_user_creation,
            "composefs_backend": self.__selected_composefs_backend,
            "image_type": self.__selected_image_type,
            "icon": self.__selected_icon,
        }

