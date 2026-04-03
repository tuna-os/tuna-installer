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
import subprocess
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

from tuna_installer.utils.progress_parser import apply_progress_event, new_progress_state


def _new_progress_state() -> dict:
    """Return a fresh progress state dict (no GTK types)."""
    return {
        "pulse_active": True,
        "current_step": 0,
        "current_total": 0,
        "current_step_name": "",
        "current_weight_pct": 0,
        "current_cumulative_pct": 0,
        "seen_substeps": set(),
        "boot_id": "",
    }


def apply_progress_event(line: str, state: dict) -> dict | None:
    """Parse one fisherman log line and return a UI-update dict, or None.

    Pure function — no GTK, no I/O.  The returned dict has:
      "fraction"  — float 0-1 for progressbar.set_fraction()
      "label"     — str for progressbar_text.set_label()
      "pulse"     — bool; True means switch bar back to pulse mode
      "complete"  — bool; True means install finished
    ``state`` is mutated in-place to track multi-line context.
    Returns None for non-JSON lines or events that require no UI change.
    """
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    event_type = event.get("type", "")

    if event_type == "step":
        step = event.get("step", 0)
        total = event.get("total_steps", 1)
        name = event.get("step_name", "Installing")
        if step <= state["current_step"] and state["current_step"] > 0:
            return None
        cumulative_pct = event.get("cumulative_pct", 0)
        state["current_weight_pct"] = event.get("weight_pct", 0)
        state["current_cumulative_pct"] = cumulative_pct
        state["current_step"] = step
        state["current_total"] = total
        state["current_step_name"] = name
        state["seen_substeps"].clear()
        state["pulse_active"] = False
        return {
            "fraction": cumulative_pct / 100.0,
            "label": "Step %d/%d: %s" % (step, total, name),
            "pulse": False,
            "complete": False,
        }

    if event_type == "substep":
        msg = event.get("message", "")
        if not msg:
            return None
        fraction = None
        m = _RE_LAYER_PROGRESS.match(msg)
        if m and state["current_weight_pct"] > 0:
            done = int(m.group(1))
            total_layers = int(m.group(2))
            sub_frac = done / total_layers
            fraction = min(
                (state["current_cumulative_pct"] + sub_frac * state["current_weight_pct"]) / 100.0,
                1.0,
            )
        if msg in state["seen_substeps"]:
            # Still update fraction even for duplicate substep messages.
            if fraction is not None:
                return {"fraction": fraction, "label": None, "pulse": False, "complete": False}
            return None
        state["seen_substeps"].add(msg)
        label = None
        if state["current_step"]:
            label = "Step %d/%d: %s — %s" % (
                state["current_step"],
                state["current_total"],
                state["current_step_name"],
                msg,
            )
        return {"fraction": fraction, "label": label, "pulse": False, "complete": False}

    if event_type == "complete":
        state["pulse_active"] = False
        state["boot_id"] = event.get("boot_id", "")
        return {"fraction": 1.0, "label": "Installation complete!", "pulse": False, "complete": True}

    return None


def _fisherman_argv_direct(recipe: str) -> list:
    """Build argv to run fisherman directly (no bash wrapper, no tee)."""
    if _IN_FLATPAK:
        if os.environ.get("TUNA_TEST"):
            bin_ = os.environ.get("TUNA_FISHERMAN_PATH", _FISHERMAN_HOST_PATH)
            return ["flatpak-spawn", "--host", "sudo", bin_, recipe]
        return ["flatpak-spawn", "--host", "pkexec", _FISHERMAN_HOST_PATH, recipe]
    elif _LIVE_ISO:
        return ["sudo", "/usr/local/bin/fisherman", recipe]
    else:
        return ["pkexec", "/usr/local/bin/fisherman", recipe]


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

from gi.repository import Gdk, Gio, GLib, Gtk, Adw

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
    log_view = Gtk.Template.Child()
    copy_log_button = Gtk.Template.Child()

    def __init__(self, window, tour: dict, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__tour = tour
        self.__proc = None       # subprocess handle for fisherman
        self.__log_out = None    # open file handle for fisherman stdout/stderr
        self.__log_buf = None    # GtkTextBuffer — set after super().__init__
        self.__pulse_active = True  # whether the progress bar is in pulse mode
        self.__log_file = None      # open handle to fisherman-output.log for tailing
        self.__log_linebuf = ""     # incomplete line buffer for the log watcher
        self.__progress_state = new_progress_state()
        self.__boot_id = ""  # EFI boot entry ID from fisherman complete event

        self.__build_ui()
        self.__log_buf = self.log_view.get_buffer()

        self.tour_button.connect("clicked", self.__on_tour_button)
        self.tour_btn_back.connect("clicked", self.__on_tour_back)
        self.tour_btn_next.connect("clicked", self.__on_tour_next)
        self.carousel_tour.connect("page-changed", self.__on_page_changed)
        self.console_button.connect("clicked", self.__on_console_button)
        self.copy_log_button.connect("clicked", self.__on_copy_log)


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

    def __on_copy_log(self, *args):
        """Copy the fisherman log to the clipboard."""
        try:
            with open(_FISHERMAN_LOG_PATH) as f:
                text = f.read()
        except OSError:
            text = self.__log_buf.get_text(
                self.__log_buf.get_start_iter(),
                self.__log_buf.get_end_iter(),
                False,
            )
        if not text:
            return
        try:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(text)
        except Exception as e:
            logger.error("Failed to copy log: %s", e)
            return
        self.copy_log_button.set_icon_name("emblem-ok-symbolic")
        GLib.timeout_add(1500, lambda: self.copy_log_button.set_icon_name("edit-copy-symbolic"))

    def __build_ui(self):
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

    def _start_log_watcher(self):
        """Begin tailing fisherman-output.log for JSON progress events.

        Polls until the file exists (fisherman creates it at startup), then
        registers a GLib.io_add_watch so the GTK main loop wakes only when
        new bytes arrive — no VTE buffer scraping, no main-loop starvation.
        """
        GLib.timeout_add(200, self.__try_open_log_for_watching)

    def __try_open_log_for_watching(self) -> bool:
        if not os.path.exists(_FISHERMAN_LOG_PATH):
            return True  # retry
        try:
            self.__log_file = open(_FISHERMAN_LOG_PATH, "r")
            GLib.io_add_watch(
                self.__log_file.fileno(),
                GLib.IOCondition.IN | GLib.IOCondition.HUP,
                self.__on_log_data,
            )
            logger.info("Log watcher started on %s", _FISHERMAN_LOG_PATH)
            return False  # stop retrying
        except OSError:
            return True  # retry

    def __on_log_data(self, fd, condition) -> bool:
        """GLib.io_add_watch callback: read new lines from the log file."""
        if condition & GLib.IOCondition.IN:
            new_text = self.__log_file.read()
            self.__log_linebuf += new_text
            lines = self.__log_linebuf.split("\n")
            self.__log_linebuf = lines[-1]  # preserve incomplete trailing line
            for line in lines[:-1]:
                self.__parse_progress_line(line.strip())
                self.__append_log_line(line)

        if condition & GLib.IOCondition.HUP:
            # Drain any remaining buffered data after the process exits.
            remaining = self.__log_file.read()
            if remaining:
                self.__log_linebuf += remaining
            for line in self.__log_linebuf.split("\n"):
                if line.strip():
                    self.__parse_progress_line(line.strip())
                    self.__append_log_line(line)
            self.__log_file.close()
            self.__log_file = None
            return False  # stop watching

        return True  # keep watching

    def __append_log_line(self, line: str):
        """Append a line to the TextView buffer and auto-scroll."""
        end = self.__log_buf.get_end_iter()
        self.__log_buf.insert(end, line + "\n")
        if self.console_box.get_visible():
            GLib.idle_add(self.__scroll_log_to_bottom)

    def __scroll_log_to_bottom(self):
        end = self.__log_buf.get_end_iter()
        self.log_view.scroll_to_iter(end, 0.0, False, 0.0, 1.0)
        return False

    def __poll_proc(self) -> bool:
        """Poll fisherman subprocess exit status every 500ms."""
        if self.__proc is None:
            return False
        ret = self.__proc.poll()
        if ret is None:
            return True  # still running
        if self.__log_out:
            self.__log_out.flush()
            self.__log_out.close()
            self.__log_out = None
        self.__window.set_installation_result(ret == 0, None, self.__boot_id)
        return False

    def __parse_progress_line(self, line: str):
        """Parse a single fisherman log line and apply any resulting UI update."""
        update = apply_progress_event(line, self.__progress_state)
        if update is None:
            return

        if update["fraction"] is not None:
            self.progressbar.set_fraction(update["fraction"])
        if update["label"] is not None:
            self.progressbar_text.set_label(_(update["label"]))
        if not update["pulse"]:
            self.__pulse_active = False

        if update["complete"]:
            self.__boot_id = self.__progress_state["boot_id"]
            logger.info("Fisherman reported completion")
        elif update.get("label"):
            logger.info("UI update: %s (fraction=%.2f)", update["label"],
                        update["fraction"] if update["fraction"] is not None else -1)

    def start(self, recipe):
        # If VANILLA_FAKE was passed as argument
        if not recipe:
            self.__window.set_installation_result(False, None)
            return

        if not _stage_fisherman_on_host():
            self.__window.set_installation_result(False, None)
            return

        argv = _fisherman_argv_direct(recipe)
        os.makedirs(_FISHERMAN_CACHE_DIR, exist_ok=True)
        self.__log_out = open(_FISHERMAN_LOG_PATH, "w", buffering=1)
        self.__proc = subprocess.Popen(
            argv,
            stdout=self.__log_out,
            stderr=subprocess.STDOUT,
        )
        GLib.timeout_add(500, self.__poll_proc)
        self._start_log_watcher()

    def update_carousel(self, slides: list):
        """Replace the carousel content with image-specific slides.

        Each slide is a dict with keys: title, description, and one of
        'image' (images.json format) or 'resource' (recipe.json format).
        Call this before start() so the carousel reflects the chosen image.
        """
        if not slides:
            return

        # Remove all existing pages.
        while self.carousel_tour.get_n_pages() > 0:
            page = self.carousel_tour.get_nth_page(0)
            self.carousel_tour.remove(page)

        for slide in slides:
            self.carousel_tour.append(VanillaTour(self.__window, slide))

        # Scroll back to first page.
        if self.carousel_tour.get_n_pages() > 0:
            self.carousel_tour.scroll_to(self.carousel_tour.get_nth_page(0), False)
        self.__on_page_changed()
