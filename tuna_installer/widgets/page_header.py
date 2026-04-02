from gi.repository import GObject, Gtk


@Gtk.Template(resource_path="/org/tunaos/Installer/gtk/widget-page-header.ui")
class TunaPageHeader(Gtk.Box):
    __gtype_name__ = "TunaPageHeader"

    _icon = Gtk.Template.Child()
    _title_label = Gtk.Template.Child()
    _subtitle_label = Gtk.Template.Child()

    @GObject.Property(type=str, default="")
    def icon_name(self):
        return self._icon.get_icon_name() or ""

    @icon_name.setter
    def icon_name(self, value):
        self._icon.set_from_icon_name(value)

    @GObject.Property(type=str, default="")
    def title(self):
        return self._title_label.get_label()

    @title.setter
    def title(self, value):
        self._title_label.set_label(value)

    @GObject.Property(type=str, default="")
    def subtitle(self):
        return self._subtitle_label.get_label()

    @subtitle.setter
    def subtitle(self, value):
        self._subtitle_label.set_label(value)
        self._subtitle_label.set_visible(bool(value))

    def set_paintable(self, paintable):
        self._icon.set_paintable(paintable)
