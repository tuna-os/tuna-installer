<div align="center">
    <img src="data/icons/hicolor/scalable/apps/org.tunaos.Installer.svg" height="64">
    <h1>TunaOS Installer</h1>
    <p>A GTK 4 / Libadwaita Flatpak installer for <a href="https://github.com/tuna-os">TunaOS</a> and other <a href="https://universal-blue.org">Universal Blue</a> bootc images.</p>
    <hr />
</div>

## Installing

Download the latest Flatpak bundle from the [Continuous Build release](https://github.com/tuna-os/tuna-installer/releases/tag/continuous) and install it:

```bash
flatpak install --user --bundle org.tunaos.Installer.flatpak
```

Or in one line with `curl`:

```bash
curl -Lo tuna-installer.flatpak \
  https://github.com/tuna-os/tuna-installer/releases/download/continuous/org.tunaos.Installer.flatpak \
  && flatpak install --user --bundle tuna-installer.flatpak
```

## Contributing Images

The installer's image catalog is defined in a single JSON file:

**[`data/images.json`](data/images.json)**

Adding a new image is as simple as adding an entry to that file. The structure is a recursive tree of groups and leaves:

```jsonc
// Group node (expandable section in the UI)
{
  "name": "My Distro",
  "subtitle": "Optional subtitle",
  "icon": "resource:///org/tunaos/Installer/images/my-distro.svg",
  "flatpaks": ["org.mozilla.firefox", "org.gnome.Console"],
  "children": [
    // Leaf node (selectable image)
    {
      "name": "Stable",
      "imgref": "ghcr.io/my-org/my-image:latest",
      "desc": "Optional description shown as tooltip"
    }
  ]
}
```

- **`flatpaks`** — list of Flatpak app IDs to install on the target system. Inherited by children if not overridden.
- **`icon`** — `resource:///org/tunaos/Installer/images/name.svg`, an absolute file path, or an XDG icon name. Drop your SVG/PNG into `data/images/` and add it to `tuna_installer/tuna-installer.gresource.xml`.
- Distros can ship a **fully custom catalog** at `/etc/tuna-installer/images.json` — it overrides the bundled one entirely.

PRs to add new images, icons, or flatpak lists are very welcome!

## Building

### Flatpak (recommended)

```bash
flatpak run org.flatpak.Builder --force-clean --user --install _build flatpak/org.tunaos.Installer.json
flatpak run org.tunaos.Installer
```

### Meson (development)

```bash
meson setup build
ninja -C build
sudo ninja -C build install
tuna-installer
```

### Dependencies

- meson, ninja
- libadwaita-1-dev
- gettext, desktop-file-utils
- libgnome-desktop-4-dev
- libgweather-4-dev
- python3-requests
- gir1.2-vte-3.91
- libnma-dev / libnma-gtk4-dev

## Custom Image Catalog Override

Distros can override the bundled image catalog without rebuilding the Flatpak:

| Path | Scope |
|---|---|
| `/etc/tuna-installer/images.json` | System-wide (distro ships this) |
| `$XDG_CONFIG_HOME/tuna-installer/images.json` | Per-user (dev/testing) |

The first file found takes priority over the bundled default.
