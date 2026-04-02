# conn_check.py
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
import os
import urllib.request
from collections import OrderedDict
from gettext import gettext as _

from gi.repository import Adw, Gtk

from tuna_installer.utils.run_async import RunAsync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VanillaInstaller::Conn_Check")


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/default-conn-check.ui")
class VanillaDefaultConnCheck(Adw.Bin):
    __gtype_name__ = "VanillaDefaultConnCheck"

    btn_recheck = Gtk.Template.Child()
    page_header = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.__step_num = step["num"]
        self.delta = False

        self.__ignore_callback = False

        # signals
        self.btn_recheck.connect("clicked", self.__on_btn_recheck_clicked)
        self.__window.carousel.connect("page-changed", self.__conn_check)
        self.__window.btn_back.connect(
            "clicked", self.__on_btn_back_clicked, self.__window.carousel.get_position()
        )

    @property
    def step_id(self):
        return self.__key

    def get_finals(self):
        return {}

    def __on_btn_back_clicked(self, data, idx):
        if idx + 1 != self.__step_num:
            return
        self.__ignore_callback = True

    def __conn_check(self, carousel=None, idx=None):
        if idx is not None and idx != self.__step_num:
            return

        def async_fn():
            if "VANILLA_SKIP_CONN_CHECK" in os.environ:
                return True

            try:
                req = urllib.request.Request(
                    "https://github.com",
                    headers={"User-Agent": "tuna-installer/0.1"}
                )
                urllib.request.urlopen(req, timeout=5)
                return True
            except Exception as e:
                logger.error(f"Connection check failed: {str(e)}")
                return False

        def callback(res, *args):
            if self.__ignore_callback:
                self.__ignore_callback = False
                return

            if res:
                self.__window.next()
                return

            self.page_header.icon_name = "network-wired-disconnected-symbolic"
            self.page_header.title = _("No Internet Connection!")
            self.page_header.subtitle = (
                _("Installer requires an active internet connection")
            )
            self.btn_recheck.set_visible(True)

        RunAsync(async_fn, callback)

    def __on_btn_recheck_clicked(self, widget, *args):
        widget.set_visible(False)
        self.page_header.icon_name = "content-loading-symbolic"
        self.page_header.title = _("Checking Connection")
        self.page_header.subtitle = (
            _("Please wait until the connection check is done")
        )
        self.__conn_check()
