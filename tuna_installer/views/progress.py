# progress.py
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

import json
import logging
import os
import re
import shutil
import stat
import time
from gettext import gettext as _

logger = logging.getLogger("Installer::Progress")

# Matches "Pulling image: layer 23/71" substep messages from fisherman.
_RE_LAYER_PROGRESS = re.compile(r"Pulling image: layer (\d+)/(\d+)")

_IN_FLATPAK = os.path.exists("/.flatpak-info")
_LIVE_ISO = not _IN_FLATPAK and os.path.exists("/run/ostree-booted")

# Where to stage fisherman so the host can see it (shared via --filesystem=host)
_FISHERMAN_CACHE_DIR = os.path.join(os.environ.get("HOME", "/tmp"), ".cache", "tuna-installer")
_FISHERMAN_HOST_PATH = os.path.join(_FISHERMAN_CACHE_DIR, "fisherman")
_FISHERMAN_LOG_PATH = os.path.join(_FISHERMAN_CACHE_DIR, "fisherman-output.log")


def _fisherman_argv(recipe: str) -> list:
    """Build the VTE argv that runs fisherman and tees combined output to a log file.

    bash is used so PIPESTATUS preserves fisherman's exit code through the tee pipe.
    """
    log = _FISHERMAN_LOG_PATH
    if _IN_FLATPAK:
        if os.environ.get("TUNA_TEST"):
            bin_ = os.environ.get("TUNA_FISHERMAN_PATH", _FISHERMAN_HOST_PATH)
            runner = f"flatpak-spawn --host sudo {bin_}"
        else:
            runner = f"flatpak-spawn --host pkexec {_FISHERMAN_HOST_PATH}"
    elif _LIVE_ISO:
        runner = "sudo /usr/local/bin/fisherman"
    else:
        runner = "pkexec /usr/local/bin/fisherman"

    return [
        "bash", "-c",
        f'{runner} "$1" 2>&1 | tee "{log}"; exit "${{PIPESTATUS[0]}}"',
        "--", recipe,
    ]


def _stage_fisherman_on_host() -> bool:
    """Copy fisherman binary to a host-visible cache dir so pkexec can find it."""
    if not _IN_FLATPAK:
        return True

    os.makedirs(_FISHERMAN_CACHE_DIR, exist_ok=True)
    fisherman_src = os.environ.get("TUNA_FISHERMAN_PATH", "/app/bin/fisherman")
    try:
        shutil.copy2(fisherman_src, _FISHERMAN_HOST_PATH)
        os.chmod(_FISHERMAN_HOST_PATH, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        logger.info(f"Staged fisherman binary to {_FISHERMAN_HOST_PATH}")
        return True
    except Exception as e:
        logger.error(f"Failed to stage fisherman binary: {e}")
        return False

from gi.repository import Gdk, Gio, GLib, Gtk, Pango, Vte, Adw

from tuna_installer.utils.run_async import RunAsync
from tuna_installer.views.tour import VanillaTour


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/progress.ui")
class VanillaProgress(Gtk.Box):
    __gtype_name__ = "VanillaProgress"

    carousel_tour = Gtk.Template.Child()
    tour_button = Gtk.Template.Child()
    tour_box = Gtk.Template.Child()
    tour_btn_back = Gtk.Template.Child()
    tour_btn_next = Gtk.Template.Child()
    progressbar = Gtk.Template.Child()
    progressbar_text = Gtk.Template.Child()
    console_button = Gtk.Template.Child()
    console_box = Gtk.Template.Child()
    console_output = Gtk.Template.Child()
    copy_log_button = Gtk.Template.Child()

    def __init__(self, window, tour: dict, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__tour = tour
        self.__terminal = Vte.Terminal()
        self.__font = Pango.FontDescription()
        self.__font.set_family("Monospace")
        self.__font.set_size(13 * Pango.SCALE)
        self.__font.set_weight(Pango.Weight.NORMAL)
        self.__font.set_stretch(Pango.Stretch.NORMAL)
        self.style_manager = Adw.StyleManager().get_default()
        self.delta = False
        self.__last_vte_lines = 0  # track how many lines we've already parsed
        self.__pulse_active = True  # whether the progress bar is in pulse mode
        self.__current_step = 0
        self.__current_total = 0
        self.__current_step_name = ""
        self.__current_weight_pct = 0
        self.__current_cumulative_pct = 0
        self.__seen_substeps = set()  # deduplicate substep messages
        self.__boot_id = ""  # EFI boot entry ID from fisherman complete event

        self.__build_ui()
        self.__on_setup_terminal_colors()

        self.style_manager.connect("notify::dark", self.__on_setup_terminal_colors)
        self.tour_button.connect("clicked", self.__on_tour_button)
        self.tour_btn_back.connect("clicked", self.__on_tour_back)
        self.tour_btn_next.connect("clicked", self.__on_tour_next)
        self.carousel_tour.connect("page-changed", self.__on_page_changed)
        self.console_button.connect("clicked", self.__on_console_button)
        self.copy_log_button.connect("clicked", self.__on_copy_log)


    def __on_setup_terminal_colors(self, *args):
          
        is_dark: bool = self.style_manager.get_dark()

        palette = [
            "#363636",
            "#c01c28",
            "#26a269",
            "#a2734c",
            "#12488b",
            "#a347ba",
            "#2aa1b3",
            "#cfcfcf",
            "#5d5d5d",
            "#f66151",
            "#33d17a",
            "#e9ad0c",
            "#2a7bde",
            "#c061cb",
            "#33c7de",
            "#ffffff",
        ]

        FOREGROUND = palette[0]
        BACKGROUND = palette[15]
        FOREGROUND_DARK = palette[15]
        BACKGROUND_DARK = palette[0]

        self.fg = Gdk.RGBA()
        self.bg = Gdk.RGBA()

        self.colors = [Gdk.RGBA() for c in palette]
        [color.parse(s) for (color, s) in zip(self.colors, palette)]
        
        if is_dark:
            self.fg.parse(FOREGROUND_DARK)
            self.bg.parse(BACKGROUND_DARK)
        else:
            self.fg.parse(FOREGROUND)
            self.bg.parse(BACKGROUND)

        self.__terminal.set_colors(self.fg, self.bg, self.colors)

    def __on_tour_button(self, *args):
        self.tour_box.set_visible(True)
        self.console_box.set_visible(False)
        self.tour_button.set_visible(False)
        self.console_button.set_visible(True)

    def __on_tour_back(self, *args):
        cur_index = self.carousel_tour.get_position()
        page = self.carousel_tour.get_nth_page(cur_index - 1)
        self.carousel_tour.scroll_to(page, True)

    def __on_tour_next(self, *args):
        cur_index = self.carousel_tour.get_position()
        page = self.carousel_tour.get_nth_page(cur_index + 1)
        self.carousel_tour.scroll_to(page, True)

    def __on_page_changed(self, *args):
        position = self.carousel_tour.get_position()
        pages = self.carousel_tour.get_n_pages()

        self.tour_btn_back.set_visible(position < pages and position > 0)
        self.tour_btn_next.set_visible(position < pages - 1)

    def __on_console_button(self, *args):
        self.tour_box.set_visible(False)
        self.console_box.set_visible(True)
        self.tour_button.set_visible(True)
        self.console_button.set_visible(False)      

    def __get_vte_text(self):
        """Extract all text from the VTE terminal, handling API differences."""
        # VTE 3.91+ (GNOME 50): get_text_format returns a plain str
        try:
            text = self.__terminal.get_text_format(Vte.Format.TEXT)
            if isinstance(text, str):
                return text
        except Exception:
            pass
        # Older VTE: get_text_range_format may return (bool, str) or str
        try:
            text = self.__terminal.get_text_range_format(
                Vte.Format.TEXT,
                0, 0,
                self.__terminal.get_cursor_position()[1],
                self.__terminal.get_column_count(),
            )
            if isinstance(text, tuple):
                return text[1] if text[0] else ""
            if isinstance(text, str):
                return text
        except Exception:
            pass
        return ""

    def __on_copy_log(self, *args):
        """Copy all VTE terminal text to the clipboard."""
        text = self.__get_vte_text().strip()
        if not text:
            return

        # Try VTE's own copy_clipboard_format first (uses the selection clipboard
        # which works reliably inside Flatpak Wayland sandboxes).
        try:
            self.__terminal.select_all()
            self.__terminal.copy_clipboard_format(Vte.Format.TEXT)
            self.__terminal.unselect_all()
            logger.info("Copied log via VTE copy_clipboard_format")
        except Exception:
            # Fallback to Gdk clipboard
            try:
                clipboard = Gdk.Display.get_default().get_clipboard()
                clipboard.set(text)
                logger.info("Copied log via Gdk clipboard")
            except Exception as e:
                # Last resort: write to a file the user can grab
                log_path = os.path.join(_FISHERMAN_CACHE_DIR, "install-log.txt")
                try:
                    with open(log_path, "w") as f:
                        f.write(text)
                    logger.info(f"Clipboard unavailable; wrote log to {log_path}")
                except Exception:
                    logger.error(f"Failed to copy log: {e}")
                    return

        # Brief visual feedback — swap icon to checkmark
        self.copy_log_button.set_icon_name("emblem-ok-symbolic")
        GLib.timeout_add(1500, lambda: self.copy_log_button.set_icon_name("edit-copy-symbolic"))

    def __build_ui(self):
        self.__terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        self.__terminal.set_font(self.__font)
        self.__terminal.set_mouse_autohide(True)
        self.__terminal.set_input_enabled(False)
        self.__terminal.set_scrollback_lines(50000)
        self.console_output.append(self.__terminal)
        self.__terminal.connect("child-exited", self.on_vte_child_exited)
        self.__terminal.connect("contents-changed", self.__on_vte_contents_changed)

        for _, tour in self.__tour.items():
            self.carousel_tour.append(VanillaTour(self.__window, tour))

        self.__start_tour()

    def __switch_tour(self, *args):
        cur_index = self.carousel_tour.get_position() + 1
        if cur_index == self.carousel_tour.get_n_pages():
            cur_index = 0

        page = self.carousel_tour.get_nth_page(cur_index)

        self.carousel_tour.scroll_to(page, True)

    def __start_tour(self):
        def run_async():
            while True:
                if self.__pulse_active:
                    GLib.idle_add(self.progressbar.pulse)
                GLib.idle_add(self.__switch_tour)
                time.sleep(5)

        RunAsync(run_async, None)

    def __on_vte_contents_changed(self, terminal):
        """Parse fisherman JSON progress lines from VTE terminal output."""
        text = self.__get_vte_text()
        if not text:
            return

        lines = text.strip().splitlines()
        total_lines = len(lines)

        # Handle scrollback buffer overflow: if the buffer shrank (old lines
        # were purged), reset our cursor to re-scan the available text.
        if total_lines < self.__last_vte_lines:
            self.__last_vte_lines = max(0, total_lines - 200)

        if total_lines <= self.__last_vte_lines:
            return

        # Only process new lines
        new_lines = lines[self.__last_vte_lines:]
        self.__last_vte_lines = total_lines

        for line in new_lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            event_type = event.get("type", "")

            if event_type == "step":
                step = event.get("step", 0)
                total = event.get("total_steps", 1)
                name = event.get("step_name", "Installing")
                # Only advance forward — ignore stale/duplicate steps.
                if step <= self.__current_step and self.__current_step > 0:
                    continue
                cumulative_pct = event.get("cumulative_pct", 0)
                self.__current_weight_pct = event.get("weight_pct", 0)
                self.__current_cumulative_pct = cumulative_pct
                fraction = cumulative_pct / 100.0
                self.__current_step = step
                self.__current_total = total
                self.__current_step_name = name
                self.__seen_substeps.clear()
                # Stop pulsing and show real progress
                self.__pulse_active = False
                self.progressbar.set_fraction(fraction)
                self.progressbar_text.set_label(
                    _("Step %d/%d: %s") % (step, total, name)
                )
                logger.info(f"Progress: step {step}/{total} — {name}")

            elif event_type == "substep":
                msg = event.get("message", "")
                if not msg:
                    continue
                # Interpolate bar within the current step's weight for layer progress.
                m = _RE_LAYER_PROGRESS.match(msg)
                if m and self.__current_weight_pct > 0:
                    done = int(m.group(1))
                    total_layers = int(m.group(2))
                    sub_frac = done / total_layers
                    bar_frac = (self.__current_cumulative_pct + sub_frac * self.__current_weight_pct) / 100.0
                    self.progressbar.set_fraction(min(bar_frac, 1.0))
                if msg not in self.__seen_substeps:
                    self.__seen_substeps.add(msg)
                    if self.__current_step:
                        self.progressbar_text.set_label(
                            _("Step %d/%d: %s — %s") % (
                                self.__current_step,
                                self.__current_total,
                                self.__current_step_name,
                                msg,
                            )
                        )
                    logger.info(f"Substep: {msg}")

            elif event_type == "info":
                msg = event.get("message", "")
                logger.info(f"Fisherman: {msg}")

            elif event_type == "complete":
                self.__pulse_active = False
                self.progressbar.set_fraction(1.0)
                self.progressbar_text.set_label(_("Installation complete!"))
                self.__boot_id = event.get("boot_id", "")
                logger.info("Fisherman reported completion")

    def on_vte_child_exited(self, terminal, status, *args):
        terminal.get_parent().remove(terminal)

        # Log the tail of the output file so the fatal error line appears in journald.
        try:
            with open(_FISHERMAN_LOG_PATH) as f:
                lines = f.readlines()
            for line in lines[-20:]:
                line = line.strip()
                if line and not line.startswith("{"):
                    logger.info(f"Fisherman: {line}")
        except Exception:
            pass

        # exit status 0 = success, anything else = failure.
        success = not bool(status)
        self.__window.set_installation_result(success, self.__terminal, self.__boot_id)

    def start(self, recipe):
        # If VANILLA_FAKE was passed as argument
        if not recipe:
            self.__window.set_installation_result(False, None)
            return

        if not _stage_fisherman_on_host():
            self.__window.set_installation_result(False, None)
            return

        self.__terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            ".",
            _fisherman_argv(recipe),
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            None,
        )
