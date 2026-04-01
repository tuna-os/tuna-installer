import os
from gettext import gettext as _

from gi.repository import Adw, Gtk


_LOG_PATH = os.path.join(
    os.environ.get("HOME", "/tmp"), ".cache", "tuna-installer", "fisherman-output.log"
)


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/dialog-output.ui")
class VanillaDialogOutput(Adw.Window):
    __gtype_name__ = "VanillaDialogOutput"

    log_view = Gtk.Template.Child()
    btn_copy = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.set_transient_for(window)

        if os.path.exists(_LOG_PATH):
            with open(_LOG_PATH) as f:
                content = f.read()
        else:
            content = _("Log not available.")

        buf = self.log_view.get_buffer()
        buf.set_text(content)
        # Scroll to end so the last (most relevant) output is visible
        self.log_view.scroll_mark_onscreen(buf.get_insert())

        self.btn_copy.connect("clicked", self.__on_copy)

    def __on_copy(self, button):
        buf = self.log_view.get_buffer()
        start, end = buf.get_bounds()
        self.get_clipboard().set(buf.get_text(start, end, False))
        self.btn_copy.set_icon_name("emblem-ok-symbolic")
