#!/usr/bin/python3 -I
"""Render the windows to PNG without putting them on screen. Run under GDK_BACKEND=broadway.

  snapshot.py install  FILE.deb OUT.png      review page after the checks
  snapshot.py checks   FILE.deb OUT.png      checks page while they run
  snapshot.py progress FILE.deb OUT.png      progress page fed with sample helper events
  snapshot.py success  FILE.deb OUT.png
  snapshot.py programs OUT.png
  snapshot.py detail   PACKAGE OUT.png
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gsk, Gtk  # noqa: E402

from debinstaller.app import App  # noqa: E402
from debinstaller.installwin import InstallWindow  # noqa: E402
from debinstaller.programswin import ProgramsWindow  # noqa: E402


def save(win, out):
    """Returns False when the window has not been laid out yet (a fresh page needs one frame)."""
    snap = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(win).snapshot(snap, win.get_width(), win.get_height())
    node = snap.to_node()  # consumes the snapshot: call once
    if node is None:
        return False
    renderer = Gsk.CairoRenderer.new()
    renderer.realize_for_display(Gdk.Display.get_default())
    renderer.render_texture(node, None).save_to_png(out)
    renderer.unrealize()
    print("saved", out, win.get_width(), "x", win.get_height())
    return True


class ShotApp(App):
    def __init__(self, mode, args):
        super().__init__()
        self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        self.mode, self.args = mode, args

    def do_activate(self):
        # Broadway has no frame clock without a browser attached: show end states, not mid-transition.
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        mode, a = self.mode, self.args
        if mode in ("install", "checks", "progress", "success"):
            win = InstallWindow(self, a[0])
            out = a[1]
        else:
            win = ProgramsWindow(self, focus=a[0] if mode == "detail" else None)
            out = a[-1]
        win.present()
        self.hold()

        def wait_report():
            if mode == "checks":
                GLib.timeout_add(int(a[2]) if len(a) > 2 else 700, finish)
                return False
            if isinstance(win, InstallWindow) and win.report is None:
                return True
            if isinstance(win, ProgramsWindow) and not win.apps:
                return True
            GLib.timeout_add(1600, stage)
            return False

        def stage():
            if mode == "progress":
                feed(win)
                GLib.timeout_add(900, finish)
            elif mode == "success":
                win._success_page()
                GLib.timeout_add(1500, finish)
            else:
                GLib.timeout_add(1200 if mode == "detail" else 300, finish)
            return False

        def finish():
            if mode == "detail":
                print("remove button sensitive:", win.remove_button.get_sensitive())
            if not save(win, out):
                win.queue_resize()
                return True
            self.release()
            self.quit()
            return False

        GLib.timeout_add(100, wait_report)


def feed(win):
    """Drive the progress page with the events the helper sends during a real install."""
    win.events_log, win.refusal, win.result, win.downgrade = [], None, None, False
    events = [{"t": "phase", "name": "verify"}, {"t": "verified", "package": "x", "version": "1"},
              {"t": "phase", "name": "apply"}]
    if any(p["old"] is None for p in win.report.deps):
        events.append({"t": "progress", "stage": "download", "pct": 60, "item": "1", "text": "Retrieving file 1 of 1 (1 380 kB/s)"})
    else:
        events.append({"t": "progress", "stage": "dpkg", "pct": 45, "item": "code", "text": "Unpacking code (amd64)"})
    events += [{"t": "log", "line": line} for line in (
        "Selecting previously unselected package code.",
        "Preparing to unpack .../tx-7f3a/pkg.deb ...",
        "Unpacking code (1.142.0-1792035033) ...")]
    for ev in events:
        win._on_event(None, ev)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    sys.exit(ShotApp(mode, args).run([sys.argv[0]]))
