"""Application entry: a .deb opens the install window, the menu icon opens the programs list."""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import APP_ID  # noqa: E402
from .installwin import InstallWindow  # noqa: E402
from .programswin import ProgramsWindow  # noqa: E402


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.programs = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self):
        self.open_programs()

    def do_open(self, files, n_files, hint):
        for f in files:
            if f.get_path():
                self.open_deb(f.get_path())

    def open_deb(self, path):
        InstallWindow(self, path).present()

    def open_programs(self, package=None):
        if self.programs is None:
            self.programs = ProgramsWindow(self, focus=package)
            self.programs.connect("destroy", lambda *_: setattr(self, "programs", None))
        elif package:
            self.programs.open_package(package)
        self.programs.present()


def main(argv=None):
    return App().run(argv if argv is not None else sys.argv)
