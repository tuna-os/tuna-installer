# main.py
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

import logging
import sys
import os

_log_file = "/var/home/james/bootc-installer-debug.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(_log_file, mode="w"),
    ],
)
logger_boot = logging.getLogger("Installer::Boot")
logger_boot.info(f"Logging to {_log_file}")

import gi
logger_boot.info("gi imported")

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
logger_boot.info("gi.require_version done")

from gi.repository import Adw, Gio
logger_boot.info("Adw/Gio imported")

from bootc_installer.widgets.page_header import TunaPageHeader  # noqa: F401 — must load before blueprints
logger_boot.info("TunaPageHeader imported")
from bootc_installer.windows.main_window import VanillaWindow
logger_boot.info("VanillaWindow imported")
from bootc_installer.windows.window_unsupported import VanillaUnsupportedWindow
from bootc_installer.windows.window_ram import VanillaRamWindow
from bootc_installer.windows.window_cpu import VanillaCpuWindow
from bootc_installer.core.system import Systeminfo
logger_boot.info("All imports done")

logger = logging.getLogger("Installer::Main")



class VanillaInstaller(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        logger.info("VanillaInstaller.__init__")
        super().__init__(
            application_id="org.bootcinstaller.Installer",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.create_action("quit", self.close, ["<primary>q"])

    def do_activate(self):
        logger.info("do_activate called")
        win = self.props.active_window
        if not win:
            try:
                logger.info("Checking system requirements")
                if "IGNORE_RAM" not in os.environ and not Systeminfo.is_ram_enough():
                    logger.info("Not enough RAM")
                    win = VanillaRamWindow(application=self)
                elif "IGNORE_CPU" not in os.environ and not Systeminfo.is_cpu_enough():
                    logger.info("Not enough CPU")
                    win = VanillaCpuWindow(application=self)
                elif not Systeminfo.is_uefi():
                    logger.info("Not UEFI")
                    win = VanillaUnsupportedWindow(application=self)
                else:
                    logger.info("Creating main window")
                    win = VanillaWindow(application=self)
                    logger.info("Main window created")
            except Exception:
                logger.exception("Fatal error in do_activate")
                self.quit()
                return
        win.present()

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def close(self, *args):
        """Close the application."""
        self.quit()


def main(version):
    """The application's entry point."""
    logger.info("Creating VanillaInstaller instance")
    app = VanillaInstaller()
    logger.info("Calling app.run()")
    ret = app.run(sys.argv)
    logger.info("app.run() returned: %s", ret)
    return ret
