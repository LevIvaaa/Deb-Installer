"""Building blocks shared by the install and the programs windows.

Every string that can come from a package is shown with markup disabled or escaped.
"""
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from .widgets import Shield

STATE_ICON = {
    "ok": ("object-select-symbolic", "success"),
    "warn": ("dialog-warning-symbolic", "warning"),
    "fail": ("dialog-error-symbolic", "error"),
    "info": ("dialog-information-symbolic", "dim-label"),
}
SEVERITY_STATE = {"critical": "fail", "warn": "warn", "info": "info"}


def label(text, *classes, wrap=False, xalign=0.0, ellipsize=None, selectable=False):
    lbl = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lbl.set_ellipsize(ellipsize)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def box(orientation, spacing, *children, **props):
    b = Gtk.Box(orientation=orientation, spacing=spacing, **props)
    for c in children:
        if c is not None:
            b.append(c)
    return b


def vbox(spacing, *children, **props):
    return box(Gtk.Orientation.VERTICAL, spacing, *children, **props)


def hbox(spacing, *children, **props):
    return box(Gtk.Orientation.HORIZONTAL, spacing, *children, **props)


def state_icon(state, size=16):
    name, cls = STATE_ICON[state]
    img = Gtk.Image.new_from_icon_name(name)
    img.set_pixel_size(size)
    img.add_css_class(cls)
    return img


def chip(text, kind=""):
    lbl = label(text, "chip")
    if kind:
        lbl.add_css_class(kind)
    return lbl


def chips(*items):
    wrap = Adw.WrapBox(child_spacing=6, line_spacing=6)
    for text, kind in items:
        wrap.append(chip(text, kind))
    return wrap


def page(*children, width=560):
    content = vbox(18, *children, margin_top=18, margin_bottom=24, margin_start=18, margin_end=18)
    return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                              child=Adw.Clamp(maximum_size=width, child=content))


def row(title, subtitle="", state=None, suffix=None):
    # Markup must be off before any text is set: constructor properties may apply in any order.
    r = Adw.ActionRow(use_markup=False)
    r.set_title(title)
    r.set_subtitle(subtitle)
    r.set_subtitle_lines(0)
    if state:
        r.add_prefix(state_icon(state))
    if suffix:
        r.add_suffix(suffix)
    return r


def expander(title, subtitle, rows, state=None, expanded=False):
    e = Adw.ExpanderRow(use_markup=False, expanded=expanded)
    e.set_title(title)
    e.set_subtitle(subtitle)
    if state:
        e.add_prefix(state_icon(state))
    for r in rows:
        e.add_row(r)
    return e


def group(title, *rows):
    g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title) if title else "")
    for r in rows:
        if r is not None:
            g.add(r)
    return g


def button(text, callback, *classes):
    b = Gtk.Button(label=text)
    b.add_css_class("pill")
    for c in classes:
        b.add_css_class(c)
    b.connect("clicked", lambda *_: callback())
    return b


def text_view(text):
    view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=10, bottom_margin=10, left_margin=12, right_margin=12)
    view.add_css_class("log")
    view.get_buffer().set_text(text)
    scroller = Gtk.ScrolledWindow(child=view, min_content_height=140, max_content_height=280,
                                  propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroller.add_css_class("log-frame")
    return scroller, view


class StatusRow(Adw.ActionRow):
    """A check that is pending, running, or finished with a result."""

    def __init__(self, title):
        super().__init__(use_markup=False)
        self.set_title(title)
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=160,
                                valign=Gtk.Align.CENTER, width_request=20, height_request=20)
        dot = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        dot.add_css_class("pending-dot")
        self._stack.add_named(dot, "pending")
        self._stack.add_named(Adw.Spinner(), "run")
        for state in ("ok", "warn", "fail"):
            icon = state_icon(state)
            icon.add_css_class("pop")
            self._stack.add_named(icon, state)
        self.add_prefix(self._stack)
        self.add_css_class("status-row")

    def set(self, state, text):
        self.set_subtitle(text or "")
        self._stack.set_visible_child_name(state)


class SecCard(Gtk.Box):
    """Verdict of the security checks with one line per check."""

    def __init__(self, verdict, results, labels):
        state, title, sub = verdict
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("sec-card")
        self.add_css_class(state)
        head_text = vbox(2, label(title, "heading", "sec-title"),
                         label(sub, "dim-label", "caption", wrap=True) if sub else None, valign=Gtk.Align.CENTER)
        self.append(hbox(12, Shield(44, state), head_text))
        for (st, text), name in zip(results, labels):
            line = label("", wrap=True)
            line.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>  "
                            f"<span alpha='70%'>{GLib.markup_escape_text(text)}</span>")
            icon = state_icon(st)
            icon.set_valign(Gtk.Align.START)
            icon.set_margin_top(2)
            self.append(hbox(8, icon, line))


def deb_icon(data, fallback="package-x-generic", size=64):
    """Icon bytes taken from the package (PNG or SVG only), or a themed fallback."""
    if data and (data.startswith(b"\x89PNG\r\n\x1a\n") or b"<svg" in data[:1024]):
        try:
            img = Gtk.Image.new_from_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
            img.set_pixel_size(size)
            img.add_css_class("app-icon")
            return img
        except GLib.Error:
            pass
    img = Gtk.Image.new_from_icon_name(fallback)
    img.set_pixel_size(size)
    img.add_css_class("app-icon")
    return img


def problem_page(problem, extra=None):
    """Blocked install or failed operation: what happened, what is affected, the raw text."""
    if problem.icon in ("virus", "shield"):
        icon = Shield(96, "bad" if problem.icon == "virus" else "warn")
    else:
        icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        icon.set_pixel_size(80)
        icon.add_css_class("error")
        icon.add_css_class("shake")
    icon.set_halign(Gtk.Align.CENTER)
    if problem.kind == "apt" and not problem.rolled_back:
        status = chip("Пакет не настроен", "warn")
    else:
        status = chip("Изменения отменены" if problem.rolled_back else "Система не изменялась", "ok")
    status.set_halign(Gtk.Align.CENTER)
    head = vbox(10, icon, label(problem.title, "title-1", wrap=True, xalign=0.5),
                label(problem.text, "dim-label", wrap=True, xalign=0.5) if problem.text else None, status)
    parts = [head]
    if problem.items:
        parts.append(group(problem.head, *[row(t, s, "fail") for t, s in problem.items]))
    advice = problem.advice
    if problem.kind == "apt" and not problem.rolled_back:
        advice = ("Исправление", "sudo dpkg --configure -a, затем удалите пакет обычным способом")
    if advice:
        parts.append(group("", row(advice[0], advice[1], "info")))
    if problem.raw:
        scroller, _ = text_view(problem.raw)
        raw = Adw.PreferencesGroup(title=GLib.markup_escape_text(problem.raw_title))
        raw.add(scroller)
        parts.append(raw)
    if extra:
        parts.append(extra)
    return page(*parts)
