"""Drawn widgets: the shield, the check mark, the removal ring and the disk usage bar."""
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Graphene, Gsk, Gtk  # noqa: E402


def anim(widget, ms, callback, easing=Adw.Easing.EASE_OUT_CUBIC, repeat=1):
    a = Adw.TimedAnimation.new(widget, 0.0, 1.0, ms, Adw.CallbackAnimationTarget.new(callback))
    a.set_easing(easing)
    a.set_repeat_count(repeat)
    return a


def _alpha(color, a):
    c = color.copy()
    c.alpha = a
    return c


def _stroke(width):
    s = Gsk.Stroke.new(width)
    s.set_line_cap(Gsk.LineCap.ROUND)
    s.set_line_join(Gsk.LineJoin.ROUND)
    return s


def _circle(cx, cy, r):
    b = Gsk.PathBuilder.new()
    b.add_circle(Graphene.Point().init(cx, cy), r)
    return b.to_path()


def _polyline(points):
    b = Gsk.PathBuilder.new()
    b.move_to(*points[0])
    for p in points[1:]:
        b.line_to(*p)
    return b.to_path()


def _draw_in(snap, points, width, progress, color):
    """Stroke a polyline as if it were being drawn: progress 0 shows nothing, 1 all of it."""
    length = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)) or 0.5
    s = _stroke(width)
    s.set_dash([length, length])
    s.set_dash_offset(length * (1 - progress))
    snap.append_stroke(_polyline(points), s, color)


class _Square(Gtk.Widget):
    def __init__(self, size):
        super().__init__()
        self._size = size

    def do_measure(self, orientation, for_size):
        return self._size, self._size, -1, -1

    def _begin(self, snap, box=64):
        w, h = self.get_width(), self.get_height()
        s = min(w, h) / box
        snap.save()
        snap.translate(Graphene.Point().init((w - box * s) / 2, (h - box * s) / 2))
        snap.scale(s, s)


class Shield(_Square):
    """Shield emblem. "run" spins a ring around it; "ok", "warn", "bad" draw a mark."""

    MARKS = {
        "ok": [[(23, 31), (29, 37), (41, 24)]],
        "warn": [[(32, 20), (32, 33)], [(32, 41), (32, 41.5)]],
        "bad": [[(25, 24), (39, 38)], [(39, 24), (25, 38)]],
    }

    def __init__(self, size=64, state="run", animate=True):
        super().__init__(size)
        self.add_css_class("shield")
        self.state, self._spin, self._mark = None, 0.0, 1.0
        self._spin_anim = anim(self, 1100, self._on_spin, Adw.Easing.LINEAR, repeat=0)
        self._mark_anim = anim(self, 500, self._on_mark)
        self.set_state(state, animate)

    def set_state(self, state, animate=True):
        if self.state:
            self.remove_css_class(self.state)
        self.state = state
        self.add_css_class(state)
        if state == "run":
            self._spin_anim.play()
        else:
            self._spin_anim.pause()
            self._mark = 0.0 if animate else 1.0
            if animate:
                self._mark_anim.play()
        self.queue_draw()

    def _on_spin(self, v):
        self._spin = v
        self.queue_draw()

    def _on_mark(self, v):
        self._mark = v
        self.queue_draw()

    def do_snapshot(self, snap):
        color = self.get_color()
        self._begin(snap)
        b = Gsk.PathBuilder.new()
        b.move_to(32, 6)
        b.line_to(52, 14)
        b.line_to(52, 28)
        b.cubic_to(52, 41, 43.4, 50.6, 32, 55)
        b.cubic_to(20.6, 50.6, 12, 41, 12, 28)
        b.line_to(12, 14)
        b.close()
        shield = b.to_path()
        snap.append_fill(shield, Gsk.FillRule.WINDING, _alpha(color, 0.14))
        snap.append_stroke(shield, _stroke(2.5), color)
        if self.state == "run":
            c = 2 * math.pi * 30
            s = _stroke(2.2)
            s.set_dash([c * 0.22, c])
            s.set_dash_offset(-self._spin * c)
            snap.append_stroke(_circle(32, 32, 30), s, color)
        else:
            for pts in self.MARKS[self.state]:
                _draw_in(snap, pts, 4.5, self._mark, color)
        snap.restore()


class CheckMark(_Square):
    """Success mark: the circle draws itself, then the tick."""

    def __init__(self, size=96):
        super().__init__(size)
        self.add_css_class("checkmark")
        self._t = 0.0
        self._anim = anim(self, 1000, self._on_t, Adw.Easing.EASE_OUT_QUART)
        self.connect("map", lambda *_: self._anim.play())

    def _on_t(self, v):
        self._t = v
        self.queue_draw()

    def do_snapshot(self, snap):
        color = self.get_color()
        self._begin(snap)
        circle_t = min(1, self._t / 0.55)
        tick_t = max(0, (self._t - 0.45) / 0.55)
        snap.append_fill(_circle(32, 32, 29), Gsk.FillRule.WINDING, _alpha(color, 0.14 * circle_t))
        c = 2 * math.pi * 29
        s = _stroke(2.5)
        s.set_dash([c, c])
        s.set_dash_offset(c * (1 - circle_t))
        snap.append_stroke(_circle(32, 32, 29), s, color)
        _draw_in(snap, [(20, 33), (28, 41), (44, 24)], 4.5, tick_t, color)
        snap.restore()


class Ring(_Square):
    """Progress ring drawn around an app icon while it is being removed."""

    def __init__(self, size):
        super().__init__(size)
        self.add_css_class("ring")
        self._value, self._from, self._to = 0.0, 0.0, 0.0
        self._anim = anim(self, 700, self._on_t)
        self.set_can_target(False)

    def set_fraction(self, value):
        self._from, self._to = self._value, value
        self._anim.reset()
        self._anim.play()

    def _on_t(self, v):
        self._value = self._from + (self._to - self._from) * v
        self.queue_draw()

    def do_snapshot(self, snap):
        if self._value <= 0:
            return
        color = self.get_color()
        self._begin(snap, 100)
        snap.translate(Graphene.Point().init(50, 50))
        snap.rotate(-90)
        snap.translate(Graphene.Point().init(-50, -50))
        c = 2 * math.pi * 47
        s = _stroke(3.5)
        s.set_dash([c * self._value, c])
        snap.append_stroke(_circle(50, 50, 47), s, color)
        snap.restore()


class StorageBar(Gtk.Widget):
    """Disk usage split by app. Segments grow in, and morph when one is removed."""

    def __init__(self):
        super().__init__()
        self.add_css_class("storage-bar")
        self._order, self._colors, self._start, self._target, self._t = [], {}, {}, {}, 1.0
        self._anim = anim(self, 850, self._on_t)

    def do_measure(self, orientation, for_size):
        return (12, 12, -1, -1) if orientation == Gtk.Orientation.VERTICAL else (40, 200, -1, -1)

    def _current(self):
        return {k: self._start.get(k, 0) + (self._target.get(k, 0) - self._start.get(k, 0)) * self._t for k in self._order}

    def set_segments(self, segments, animate=True):
        """segments: [(key, value, Gdk.RGBA)] in display order."""
        total = sum(v for _, v, _ in segments) or 1
        self._start = self._current() if animate else {}
        self._target = {k: v / total for k, v, _ in segments}
        self._order += [k for k, _, _ in segments if k not in self._order]
        self._colors.update({k: c for k, _, c in segments})
        if animate:
            self._t = 0.0
            self._anim.reset()
            self._anim.play()
        else:
            self._t = 1.0
            self.queue_draw()

    def _on_t(self, v):
        self._t = v
        self.queue_draw()

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        rect = Graphene.Rect().init(0, 0, w, h)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(rect, h / 2)
        snap.push_rounded_clip(rounded)
        snap.append_color(_alpha(self.get_color(), 0.08), rect)
        x = 0.0
        for k, f in self._current().items():
            width = f * w
            if width > 0.5:
                snap.append_color(self._colors[k], Graphene.Rect().init(x, 0, max(width - 2, 0.5), h))
            x += width
        snap.pop()


class Dot(Gtk.Widget):
    """A small colour dot for legends."""

    def __init__(self, color, size=8):
        super().__init__(valign=Gtk.Align.CENTER)
        self._color, self._size = color, size

    def do_measure(self, orientation, for_size):
        return self._size, self._size, -1, -1

    def do_snapshot(self, snap):
        rect = Graphene.Rect().init(0, 0, self._size, self._size)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(rect, self._size / 2)
        snap.push_rounded_clip(rounded)
        snap.append_color(self._color, rect)
        snap.pop()


PALETTE = ["#3584e4", "#2190a4", "#3a944a", "#c88800", "#ed5b00", "#e62d42", "#d56199", "#9141ac", "#6f8396"]


def palette(i):
    c = Gdk.RGBA()
    c.parse(PALETTE[i % len(PALETTE)])
    return c
