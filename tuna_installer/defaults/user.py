import re
import logging

from gi.repository import Adw, Gtk

logger = logging.getLogger("Installer::User")

# Groups added to every created user.
_DEFAULT_GROUPS = ["wheel"]


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/default-users.ui")
class VanillaDefaultUsers(Adw.Bin):
    __gtype_name__ = "VanillaDefaultUsers"

    btn_next           = Gtk.Template.Child()
    status_page        = Gtk.Template.Child()
    fullname_entry     = Gtk.Template.Child()
    username_entry     = Gtk.Template.Child()
    password_entry     = Gtk.Template.Child()
    password_confirmation = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__key = key
        self.__step = step
        self.delta = False

        self.fullname_entry.connect("changed", self.__on_fullname_changed)
        self.username_entry.connect("changed", self.__on_field_changed)
        self.password_entry.connect("changed", self.__on_field_changed)
        self.password_confirmation.connect("changed", self.__on_field_changed)
        self.btn_next.connect("clicked", self.__window.next)

        self.__update_btn_next()

    @property
    def skip_screen(self) -> bool:
        """Skip this step unless the selected image requires user creation."""
        image_step = getattr(self.__window, "image_step", None)
        if image_step is None:
            return False
        return not image_step.selected_needs_user_creation

    def test_auto_advance(self):
        self.btn_next.emit("clicked")

    def get_finals(self):
        username = self.username_entry.get_text().strip()
        if not username:
            return {"user": {"username": "", "fullname": "", "password": "", "groups": []}}
        return {
            "user": {
                "username": username,
                "fullname": self.fullname_entry.get_text().strip(),
                "password": self.password_entry.get_text(),
                "groups": _DEFAULT_GROUPS,
            }
        }

    # ── Handlers ──────────────────────────────────────────────────────────────

    def __on_fullname_changed(self, entry):
        """Auto-suggest a username from the full name."""
        fullname = entry.get_text()
        current_username = self.username_entry.get_text()
        # Only auto-fill if the user hasn't typed a username yet.
        if current_username == "" or current_username == self.__suggested_username(
            self.__prev_fullname if hasattr(self, "_VanillaDefaultUsers__prev_fullname") else ""
        ):
            suggested = self.__suggested_username(fullname)
            self.username_entry.set_text(suggested)
        self.__prev_fullname = fullname
        self.__on_field_changed(entry)

    def __suggested_username(self, fullname: str) -> str:
        """Derive a lowercase alphanumeric username from a full name."""
        name = fullname.lower().split()[0] if fullname.strip() else ""
        return re.sub(r"[^a-z0-9_-]", "", name)

    def __on_field_changed(self, *args):
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text()
        confirm  = self.password_confirmation.get_text()

        # Username: must start with letter/underscore, only lowercase alnum + _ -
        username_ok = bool(re.match(r"^[a-z_][a-z0-9_-]{0,31}$", username)) if username else False

        if username and not username_ok:
            self.username_entry.add_css_class("error")
        else:
            self.username_entry.remove_css_class("error")

        passwords_match = password == confirm and bool(password)
        if confirm and not passwords_match:
            self.password_confirmation.add_css_class("error")
        else:
            self.password_confirmation.remove_css_class("error")

        self.__update_btn_next()

    def __update_btn_next(self):
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text()
        confirm  = self.password_confirmation.get_text()

        username_ok = bool(re.match(r"^[a-z_][a-z0-9_-]{0,31}$", username)) if username else False
        passwords_match = password == confirm and bool(password)

        self.btn_next.set_sensitive(username_ok and passwords_match)
