"""Programs installed outside Ubuntu: disk usage, search and removal."""
import threading

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import errors, system, text
from .helperclient import HelperRun
from .ui import button, chip, chips, group, hbox, label, page, row, state_icon, vbox
from .widgets import Dot, Ring, StorageBar, anim, palette


def _app_icon(app, size):
    info = Gio.DesktopAppInfo.new_from_filename(app.desktop)
    gicon = info.get_icon() if info else None
    img = Gtk.Image.new_from_gicon(gicon) if gicon else Gtk.Image.new_from_icon_name("application-x-executable")
    img.set_pixel_size(size)
    img.add_css_class("app-icon")
    return img


class ProgramsWindow(Adw.ApplicationWindow):
    def __init__(self, app, focus=None):
        super().__init__(application=app, default_width=780, default_height=840, title="Программы")
        self.app, self.focus = app, focus
        self.apps, self.cards, self.colors, self.busy = [], {}, {}, False
        self.nav = Adw.NavigationView()
        self.toasts = Adw.ToastOverlay(child=self.nav)
        self.set_content(self.toasts)
        self.nav.add(self._list_page())
        self.connect("close-request", self._on_close)
        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)
        self._shown_total = 0.0
        self._total_anim = None
        threading.Thread(target=lambda: GLib.idle_add(self._loaded, system.third_party_apps()), daemon=True).start()

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=3))

    def _on_close(self, *_):
        if self.busy:
            self.toast("Дождитесь окончания удаления")
            return True
        return False

    # -- list -------------------------------------------------------------------------------------
    def _list_page(self):
        self.search = Gtk.SearchEntry(placeholder_text="Найти программу", hexpand=True)
        self.search.connect("search-changed", lambda *_: self._apply_filter())
        open_file = Gtk.Button(child=Adw.ButtonContent(icon_name="document-open-symbolic", label="Установить из файла"))
        open_file.connect("clicked", self._choose_file)
        self.total, self.unit = label("0", "storage-num"), label("", "storage-unit")
        self.total.set_valign(Gtk.Align.BASELINE_FILL)
        self.unit.set_valign(Gtk.Align.BASELINE_FILL)
        caption = label("установлено вами", "dim-label")
        caption.set_valign(Gtk.Align.BASELINE_FILL)
        caption.set_margin_start(6)
        self.bar = StorageBar()
        self.legend = Adw.WrapBox(child_spacing=16, line_spacing=4)
        storage = vbox(12, hbox(6, self.total, self.unit, caption), self.bar, self.legend)
        storage.add_css_class("card")
        storage.add_css_class("storage-card")
        self.filters = Adw.ToggleGroup(halign=Gtk.Align.START)
        self.filters.add(Adw.Toggle(name="all", label="Все"))
        self.filters.add(Adw.Toggle(name="noupd", label="Без обновлений"))
        self.filters.connect("notify::active-name", lambda *_: self._apply_filter())
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
                                max_children_per_line=4, column_spacing=10, row_spacing=10)
        self.flow.set_filter_func(self._visible)
        self.loading = Adw.Spinner(height_request=40)
        self.empty = label("Ничего не нашлось", "dim-label", xalign=0.5)
        self.empty.set_visible(False)
        protect = Gtk.Button()
        protect.add_css_class("protect")
        caption_protect = label("Системные программы защищены")
        caption_protect.set_hexpand(True)
        protect.set_child(hbox(12, Gtk.Image.new_from_icon_name("channel-secure-symbolic"), caption_protect,
                               Gtk.Image.new_from_icon_name("go-next-symbolic")))
        protect.connect("clicked", self._explain_protection)
        body = page(hbox(10, self.search, open_file), storage, self.filters, self.loading, self.flow, self.empty,
                    protect, width=760)
        view = Adw.ToolbarView(content=body)
        view.add_top_bar(Adw.HeaderBar())
        return Adw.NavigationPage(title="Программы", tag="list", child=view)

    def _loaded(self, apps):
        self.apps = apps
        self.loading.set_visible(False)
        for i, a in enumerate(apps):
            self.colors[a.package] = palette(i)
            self._add_card(a, i)
        self._refresh(animate=True)
        if self.focus:
            self.open_package(self.focus)
        return False

    def _add_card(self, a, i):
        badge = chip("Обновляется" if a.host else "Без обновлений", "ok" if a.host else "warn")
        badge.set_halign(Gtk.Align.START)
        badge.set_margin_top(4)
        icon = _app_icon(a, 48)
        icon.set_halign(Gtk.Align.START)
        icon.set_margin_bottom(6)
        name = label(a.name, "heading", ellipsize=Pango.EllipsizeMode.END)
        content = vbox(2, icon, name, label(text.size(a.size_kb * 1024), "dim-label", "numeric"), badge)
        card = Gtk.Button(child=content)
        card.add_css_class("card")
        card.add_css_class("app-card")
        card.connect("clicked", lambda *_: self._open(a))
        reveal = Gtk.Revealer(child=card, transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                              transition_duration=380)
        child = Gtk.FlowBoxChild(child=reveal, focusable=False)
        child.app = a
        self.flow.append(child)
        self.cards[a.package] = (child, reveal)
        GLib.timeout_add(45 * i + 60, lambda: reveal.set_reveal_child(True) or False)

    def _visible(self, child):
        q = self.search.get_text().strip().lower()
        a = child.app
        if q and q not in a.name.lower() and q not in a.package:
            return False
        return self.filters.get_active_name() != "noupd" or not a.host

    def _apply_filter(self):
        self.flow.invalidate_filter()
        self.empty.set_visible(bool(self.apps) and not any(self._visible(c) for c, _ in self.cards.values()))

    def _refresh(self, animate):
        total = sum(a.size_kb for a in self.apps) * 1024
        self._count_to(total, animate)
        self.bar.set_segments([(a.package, a.size_kb, self.colors[a.package]) for a in self.apps], animate)
        while child := self.legend.get_first_child():
            self.legend.remove(child)
        for a in self.apps[:3]:
            self.legend.append(hbox(6, Dot(self.colors[a.package]),
                                    label(f"{a.name} · {text.size(a.size_kb * 1024)}", "dim-label", "caption")))
        if len(self.apps) > 3:
            self.legend.append(label(f"и ещё {len(self.apps) - 3}", "dim-label", "caption"))
        n_noupd = sum(1 for a in self.apps if not a.host)
        self.filters.get_toggle_by_name("all").set_label(f"Все · {len(self.apps)}")
        self.filters.get_toggle_by_name("noupd").set_label(f"Без обновлений · {n_noupd}")

    def _count_to(self, target, animate):
        start = self._shown_total

        def show(v):
            self._shown_total = start + (target - start) * v
            number, _, unit = text.size(int(self._shown_total)).rpartition(" ")
            self.total.set_text(number or "0")
            self.unit.set_text(unit)

        if not animate:
            show(1.0)
            return
        self._total_anim = anim(self, 900, show, Adw.Easing.EASE_OUT_CUBIC)
        self._total_anim.play()

    # -- details and removal -------------------------------------------------------------------------
    def open_package(self, package):
        for a in self.apps:
            if a.package == package:
                self._open(a)
                return

    def _open(self, a):
        self.current, self.expected = a, []
        self.icon = _app_icon(a, 96)
        holder = Gtk.CenterBox(width_request=124, height_request=124, center_widget=self.icon)
        holder.set_hexpand(False)
        self.ring = Ring(124)
        overlay = Gtk.Overlay(child=holder, valign=Gtk.Align.CENTER)
        overlay.add_overlay(self.ring)
        self.detail_title = label(a.name, "title-1", wrap=True)
        self.detail_meta = label(f"{a.package} · {a.version}", "dim-label", "caption", "monospace", wrap=True)
        source = ("Обновляется из " + system.vendor(a.host), "ok") if a.host else ("Без источника обновлений", "warn")
        hero = hbox(22, overlay, vbox(4, self.detail_title, self.detail_meta, chips(source), valign=Gtk.Align.CENTER))
        self.what = row("Что удалится", "Проверка…")
        self.what_icon = Gtk.Stack(width_request=16)
        self.what_icon.add_named(Adw.Spinner(), "run")
        for state in ("ok", "warn", "fail"):
            self.what_icon.add_named(state_icon(state), state)
        self.what.add_prefix(self.what_icon)
        rows = [row("Занимает на диске", text.size(a.size_kb * 1024)), self.what,
                row("Ваши данные", "Останутся в домашней папке")]
        if not a.host:
            rows.append(row("Не получает обновлений безопасности", "", "warn"))
        self.purge = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        purge_row = Adw.ActionRow(title="Удалить и системные настройки", subtitle="Файлы программы в /etc",
                                  use_markup=False, activatable_widget=self.purge)
        purge_row.add_prefix(self.purge)
        self.remove_button = button(f"Удалить {a.name}", lambda: self._remove(a), "destructive-action")
        self.remove_button.set_sensitive(False)
        self.detail_actions = hbox(10, Gtk.Box(hexpand=True), self.remove_button,
                                   margin_top=10, margin_bottom=14, margin_start=18, margin_end=18)
        view = Adw.ToolbarView(content=page(hero, group("", *rows), group("", purge_row), width=640))
        view.add_top_bar(Adw.HeaderBar())
        view.add_bottom_bar(self.detail_actions)
        self.detail = Adw.NavigationPage(title=a.name, child=view)
        self.nav.push(self.detail)
        threading.Thread(target=self._simulate, args=(a, self.detail), daemon=True).start()

    def _simulate(self, a, page_ref):
        sim = system.simulate_remove(a.package)
        blocked = [n for n in sim.removes if system.is_protected(n)]
        GLib.idle_add(self._simulated, a, page_ref, sim, blocked)

    def _simulated(self, a, page_ref, sim, blocked):
        if page_ref is not self.detail:
            return False
        others = [n for n in sim.removes if n != a.package]
        if sim.rc != 0 or a.package not in sim.removes:
            state, value = "fail", "APT не может удалить этот пакет"
        elif blocked:
            state, value = "fail", "Задело бы системные пакеты: " + ", ".join(blocked)
        elif others:
            state, value = "warn", f"{a.package} и зависящие от него: " + ", ".join(others)
        else:
            state, value = "ok", f"Только {a.package}"
        self.what.set_subtitle(value)
        self.what_icon.set_visible_child_name(state)
        if state != "fail":
            self.expected = sim.removes
            self.remove_button.set_sensitive(True)
        return False

    def _remove(self, a):
        self.remove_button.set_sensitive(False)
        self.outcome = {"done": None, "refused": None, "log": []}
        run = HelperRun.remove(a.package, self.expected, purge=self.purge.get_active())
        run.connect("event", lambda _r, ev: self._on_event(ev))
        run.connect("finished", lambda r, status: self._finished(a, r, status))

    def _on_event(self, ev):
        kind = ev.get("t")
        if kind == "phase" and not self.busy:
            self.busy = True
            self.detail.set_can_pop(False)
            self.ring.set_fraction(0.12)
            spinner = Adw.Spinner()
            spinner.add_css_class("ring")
            self._set_detail_actions(hbox(8, spinner, label(f"Удаляем {self.current.name}…", "dim-label")))
        elif kind == "progress":
            self.ring.set_fraction(max(0.12, float(ev.get("pct", 0)) / 100 * 0.95))
        elif kind == "log":
            self.outcome["log"].append(ev.get("line", ""))
        elif kind == "refused":
            self.outcome["refused"] = (ev.get("reason", ""), ev.get("detail", ""))
        elif kind == "done":
            self.outcome["done"] = ev

    def _set_detail_actions(self, widget):
        while child := self.detail_actions.get_first_child():
            self.detail_actions.remove(child)
        self.detail_actions.append(Gtk.Box(hexpand=True))
        self.detail_actions.append(widget)

    def _finished(self, a, run, status):
        self.busy = False
        self.detail.set_can_pop(True)
        if run.cancelled:
            self.remove_button.set_sensitive(True)
            self.toast("Удаление отменено")
            return
        done = self.outcome["done"]
        if done and done.get("ok"):
            self.ring.set_fraction(1.0)
            self.icon.add_css_class("gone")
            self.detail_title.set_text(f"{a.name} удалён")
            self.detail_meta.set_text(f"Освободилось {text.size(a.size_kb * 1024)}")
            done_chip = chip("Готово", "ok")
            self._set_detail_actions(done_chip)
            GLib.timeout_add(1400, lambda: self._back_after_removal(a) or False)
            return
        if self.outcome["refused"]:
            problem = errors.refused(*self.outcome["refused"])
        else:
            problem = errors.apt_failure("\n".join(self.outcome["log"]), False, a.name)
            problem.title = f"Не удалось удалить {a.name}"
        self.ring.set_fraction(0)
        self._set_detail_actions(self.remove_button)
        self.remove_button.set_sensitive(True)
        dialog = Adw.AlertDialog(heading=problem.title, body=problem.text or problem.raw[-400:])
        dialog.add_response("ok", "Закрыть")
        dialog.present(self)

    def _back_after_removal(self, a):
        self.nav.pop()
        child, reveal = self.cards.pop(a.package)
        reveal.set_reveal_child(False)
        GLib.timeout_add(400, lambda: self.flow.remove(child) or False)
        self.apps = [x for x in self.apps if x.package != a.package]
        self._refresh(animate=True)
        self.toast(f"Удалено: {a.name} · освободилось {text.size(a.size_kb * 1024)}")

    # -- other entry points ---------------------------------------------------------------------------
    def _explain_protection(self, *_):
        dialog = Adw.AlertDialog(heading="Системные программы защищены",
                                 body="Пакеты, без которых не работает Ubuntu, отсюда не удаляются.")
        dialog.add_response("ok", "Понятно")
        dialog.present(self)

    def _choose_file(self, *_):
        filt = Gtk.FileFilter(name="Пакеты .deb")
        filt.add_mime_type("application/vnd.debian.binary-package")
        filt.add_pattern("*.deb")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        Gtk.FileDialog(title="Выберите .deb-файл", filters=filters).open(self, None, self._file_chosen)

    def _file_chosen(self, dialog, result):
        try:
            f = dialog.open_finish(result)
        except GLib.Error:
            return
        if f and f.get_path():
            self.app.open_deb(f.get_path())

    def _on_drop(self, target, value, x, y):
        path = value.get_path() if value else None
        if path and path.endswith(".deb"):
            self.app.open_deb(path)
            return True
        self.toast("Это не .deb-файл")
        return False
