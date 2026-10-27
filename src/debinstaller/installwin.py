"""The window that opens for a .deb: checks, confirmation, progress, result."""
import math
import os
import threading
import traceback

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import analysis, errors, system, text
from .helperclient import HelperRun
from .ui import (SEVERITY_STATE, SecCard, StatusRow, button, chips, deb_icon, expander, group, hbox, label, page,
                 problem_page, row, state_icon, text_view, vbox)
from .widgets import CheckMark, Shield, anim

ACTION_BUTTON = {"install": "Установить", "reinstall": "Переустановить", "upgrade": "Обновить"}
DONE_TITLE = {"install": "установлен", "reinstall": "переустановлен", "upgrade": "обновлён", "downgrade": "понижен"}


class InstallWindow(Adw.ApplicationWindow):
    def __init__(self, app, path):
        super().__init__(application=app, default_width=560, default_height=760)
        self.app, self.path = app, os.path.abspath(path)
        self.report, self.run, self.busy, self._inhibit = None, None, False, 0
        self.downgrade, self.refusal, self.result = False, None, None
        self.title = Adw.WindowTitle(title="Установка пакета", subtitle=os.path.basename(path))
        header = Adw.HeaderBar(title_widget=self.title)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT, transition_duration=320)
        self.stack.connect("notify::transition-running", self._drop_old_pages)
        self.actions = hbox(10, margin_top=10, margin_bottom=14, margin_start=18, margin_end=18)
        self.bar = Gtk.Revealer(child=self.actions, reveal_child=True,
                                transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        self.view = Adw.ToolbarView(content=self.stack)
        self.view.add_top_bar(header)
        self.view.add_bottom_bar(self.bar)
        self.toasts = Adw.ToastOverlay(child=self.view)
        self.set_content(self.toasts)
        self.connect("close-request", self._on_close)
        self._shake_anim = anim(self, 520, self._on_shake, Adw.Easing.LINEAR)
        self._analysis_page()

    # -- plumbing -------------------------------------------------------------------------------
    def _show(self, widget, title=None):
        self.stack.add_child(widget)
        self.stack.set_visible_child(widget)
        if title:
            self.title.set_title(title)

    def _drop_old_pages(self, stack, _):
        if not stack.get_transition_running():
            for child in list(stack):
                if child is not stack.get_visible_child():
                    stack.remove(child)

    def _set_actions(self, start=None, *end):
        while child := self.actions.get_first_child():
            self.actions.remove(child)
        if start:
            self.actions.append(start)
        self.actions.append(Gtk.Box(hexpand=True))
        for b in end:
            self.actions.append(b)
        self.bar.set_reveal_child(bool(start or end))

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=3))

    def _on_close(self, *_):
        if not self.busy:
            return False
        self.toast("Дождитесь окончания установки")
        self._shake_anim.reset()
        self._shake_anim.play()
        return True

    def _on_shake(self, v):
        x = int(10 * math.sin(v * math.pi * 6) * (1 - v))
        self.view.set_margin_start(max(0, x))
        self.view.set_margin_end(max(0, -x))

    # -- checks -----------------------------------------------------------------------------------
    def _analysis_page(self):
        self.shield = Shield(64, "run")
        self.hero_title = label("Проверяем пакет", "title-2")
        name = label(os.path.basename(self.path), "dim-label", "caption", "monospace",
                     ellipsize=Pango.EllipsizeMode.MIDDLE)
        hero = hbox(16, self.shield, vbox(2, self.hero_title, name, valign=Gtk.Align.CENTER))
        self.rows = {"pkg": [StatusRow(t) for t in analysis.PKG_ROWS],
                     "sec": [StatusRow(t) for t in analysis.SEC_ROWS]}
        self._show(page(hero, group("Пакет", *self.rows["pkg"]), group("Безопасность", *self.rows["sec"])))
        self._set_actions(None, button("Отмена", self.close))
        threading.Thread(target=self._analyze, daemon=True).start()

    def _analyze(self):
        try:
            report = analysis.analyze(self.path, lambda *a: GLib.idle_add(self._on_row, *a))
        except Exception:  # noqa: BLE001 - shown to the user instead of a silent dead window
            report = analysis.Report(path=self.path, size=0)
            report.problem = errors.Problem("internal", "err", "Не удалось проверить пакет",
                                            raw_title="Подробности", raw=traceback.format_exc())
        GLib.idle_add(self._on_report, report)

    def _on_row(self, group_name, i, state, value):
        self.rows[group_name][i].set(state, value)
        return False

    def _on_report(self, report):
        self.report = report
        state, title = report.verdict[:2]
        if report.problem:
            state = "bad" if report.problem.icon == "virus" else "warn" if report.problem.icon == "shield" else "bad"
            title = report.problem.title
        self.shield.set_state(state)
        self.hero_title.set_text(title)
        for cls in ("success", "warning", "error"):
            self.hero_title.remove_css_class(cls)
        self.hero_title.add_css_class({"ok": "success", "warn": "warning", "bad": "error"}[state])
        GLib.timeout_add(950, self._after_analysis)
        return False

    def _after_analysis(self):
        r = self.report
        if r.problem:
            self._problem(r.problem)
        elif r.action == "downgrade":
            self._downgrade_page()
        else:
            self._review_page()
        return False

    # -- confirmation -----------------------------------------------------------------------------
    def _display_name(self):
        d = self.report.deb
        return d.desktop.get("Name[ru]") or d.desktop.get("Name") or d.name

    def _hero(self, size=64):
        d = self.report.deb
        meta = label(f"{d.name} · {d.version}", "dim-label", "caption", "monospace", wrap=True)
        lines = [label(self._display_name(), "title-2" if size >= 64 else "title-4", wrap=True), meta]
        if size >= 64 and d.summary:
            lines.append(label(d.summary, "dim-label", wrap=True))
        return hbox(16, deb_icon(d.icon, size=size), vbox(2, *lines, valign=Gtk.Align.CENTER))

    def _source_chip(self):
        r = self.report
        if r.update_host:
            return f"Обновления из {system.vendor(r.update_host)}", "ok"
        if any(f.title == "Подключит репозиторий" for f in r.findings):
            return "Подключит свой репозиторий", "ok"
        return "Без источника обновлений", "warn"

    def _details(self):
        r, d = self.report, self.report.deb
        installed_size = int(d.fields.get("Installed-Size", "0") or 0) * 1024
        rows = [row("Размер", f"{text.size(r.size)} файл · {text.size(installed_size)} после установки")]
        fetch = [p for p in r.deps if p["old"] is None]
        upgrade = [p for p in r.deps if p["old"] is not None]
        if r.deps:
            sub = text.packages(len(fetch)) + (f", обновится {len(upgrade)}" if upgrade else "")
            rows.append(expander("Докачается из репозиториев", sub, [
                row(p["name"], f"{p['new']} · {p['origin']}" + (f" · сейчас {p['old']}" if p["old"] else ""))
                for p in r.deps]))
        else:
            rows.append(row("Зависимости", "Все установлены", "ok"))
        if r.findings:
            worst = SEVERITY_STATE[r.findings[0].severity]
            rows.append(expander("Действия при установке", "Есть на что посмотреть" if worst == "warn" else "Опасных нет",
                                 [row(f.title, f.detail, SEVERITY_STATE[f.severity]) for f in r.findings]))
        copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Копировать")
        copy.add_css_class("flat")
        copy.connect("clicked", lambda *_: (self.get_clipboard().set(d.sha256), self.toast("SHA-256 скопирован")))
        rows.append(row("Отпечаток SHA-256", f"{d.sha256[:8]}…{d.sha256[-6:]}", suffix=copy))
        return group("", *rows)

    def _review_page(self):
        r = self.report
        first = {"install": ("Новая установка", "accent"), "reinstall": ("Эта версия уже установлена", ""),
                 "upgrade": (f"Обновление {r.installed} → {r.deb.version}", "accent")}[r.action]
        self._show(page(self._hero(), chips(first, self._source_chip()),
                        SecCard(r.verdict, r.sec, analysis.SEC_ROWS), self._details()))
        self.install_button = button(ACTION_BUTTON[r.action], self._install, "suggested-action")
        self._set_actions(None, button("Отмена", self.close), self.install_button)

    def _downgrade_page(self):
        r, d = self.report, self.report.deb
        lower = row(f"Понизить до {d.version}", "",
                    suffix=button("Понизить", lambda: self._install(downgrade=True), "destructive-action"))
        rows = [row("Файл старее установленной версии", f"Установлена {r.installed} · в файле {d.version}", "warn"),
                expander("Установить старую версию", "Может нарушить настройки программы", [lower], "warn")]
        self._show(page(self._hero(), chips(("Старая версия", "warn"), self._source_chip()),
                        SecCard(r.verdict, r.sec, analysis.SEC_ROWS), group("", *rows)), "Пакет уже установлен")
        self._set_actions(button("Удалить программу…", lambda: self.app.open_programs(d.name), "flat", "destructive"),
                          button("Закрыть", self.close, "suggested-action"))

    # -- install ----------------------------------------------------------------------------------
    def _install(self, downgrade=False):
        r = self.report
        for child in list(self.actions):
            child.set_sensitive(False)
        self.events_log, self.refusal, self.result, self.downgrade = [], None, None, downgrade
        self.run = HelperRun.install(r.path, r.deb.sha256, r.size, reinstall=r.action == "reinstall",
                                     downgrade=downgrade)
        self.run.connect("event", self._on_event)
        self.run.connect("finished", self._on_finished)

    def _progress_page(self):
        r = self.report
        fetch = [p for p in r.deps if p["old"] is None]
        names = ["Проверка файла"] + ([f"Скачивание {text.packages_genitive(len(fetch))}"] if fetch else []) \
            + ["Распаковка", "Настройка"]
        self.steps = []
        step_rows = []
        for name in names:
            icon = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, width_request=20, height_request=20)
            dot = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            dot.add_css_class("pending-dot")
            icon.add_named(dot, "pending")
            icon.add_named(Adw.Spinner(), "run")
            done = state_icon("ok")
            done.add_css_class("pop")
            icon.add_named(done, "ok")
            failed = state_icon("fail")
            failed.add_css_class("pop")
            icon.add_named(failed, "fail")
            lbl = label(name, "step")
            self.steps.append((icon, lbl))
            step_rows.append(hbox(12, icon, lbl))
        self.step_names, self.step_i = names, -1
        self.stage = label("Подготовка", "title-3")
        self.bar_widget = Gtk.ProgressBar()
        self.bar_from, self.bar_to = 0.0, 0.0
        self.bar_anim = anim(self, 400, self._on_bar)
        self.item = label("", "dim-label", "caption", ellipsize=Pango.EllipsizeMode.END)
        self.item.set_hexpand(True)
        self.rolling_back = False
        self.pct = label("0 %", "dim-label", "caption", "numeric")
        scroller, self.log_view = text_view("")
        details = Adw.ExpanderRow(title="Подробности", use_markup=False)
        details.add_row(Adw.PreferencesRow(child=scroller, activatable=False))
        self._show(page(self._hero(48), vbox(8, self.stage, self.bar_widget, hbox(12, self.item, self.pct)),
                        vbox(6, *step_rows), group("", details)),
                   "Понижение версии" if self.downgrade else "Установка")
        self._set_actions(None)
        self._step(0)

    def _step(self, i):
        if i <= self.step_i or i >= len(self.steps):
            return
        if self.step_i >= 0:
            self.steps[self.step_i][0].set_visible_child_name("ok")
            self.steps[self.step_i][1].remove_css_class("active")
        self.step_i = i
        self.steps[i][0].set_visible_child_name("run")
        self.steps[i][1].add_css_class("active")

    def _set_bar(self, fraction, item=None):
        self.bar_from, self.bar_to = self.bar_widget.get_fraction(), max(0.0, min(1.0, fraction))
        self.bar_anim.reset()
        self.bar_anim.play()
        self.pct.set_text(f"{round(self.bar_to * 100)} %")
        if item is not None:
            self.item.set_text(item)

    def _on_bar(self, v):
        self.bar_widget.set_fraction(self.bar_from + (self.bar_to - self.bar_from) * v)

    def _log(self, line):
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")
        self.log_view.scroll_to_mark(buf.get_insert(), 0, False, 0, 1)

    def _on_event(self, run, ev):
        kind = ev.get("t")
        if kind == "refused":
            self.refusal = (ev.get("reason", ""), ev.get("detail", ""))
        elif kind == "done":
            self.result = ev
        if kind == "phase" and ev.get("name") == "verify":
            self.busy = True
            self._inhibit = self.app.inhibit(self, Gtk.ApplicationInhibitFlags.LOGOUT | Gtk.ApplicationInhibitFlags.SUSPEND,
                                             "Идёт установка пакета")
            self._progress_page()
            self.stage.set_text("Проверка файла")
            self._set_bar(0.03, "Сверка отпечатка")
        elif not hasattr(self, "steps"):
            return
        elif kind == "verified":
            self._set_bar(0.06, "Отпечаток совпадает")
        elif kind == "phase" and ev.get("name") == "apply":
            downloading = len(self.step_names) == 4
            self._step(1)
            self.stage.set_text("Скачивание зависимостей" if downloading else "Распаковка")
        elif kind == "phase" and ev.get("name") == "update":
            self.stage.set_text("Обновление списков пакетов")
        elif kind == "phase" and ev.get("name") == "rollback":
            self.rolling_back = True
            self.steps[self.step_i][0].set_visible_child_name("fail")
            self.stage.set_text("Откат изменений")
            self.bar_widget.add_css_class("rollback")
            self.bar_widget.set_fraction(0)
            self._set_bar(0.1, ", ".join(ev.get("packages", [])))
        elif kind == "progress":
            pct, raw = float(ev.get("pct", 0)), ev.get("text", "")
            words = text.apt_status(raw)
            dl = len(self.step_names) == 4
            if self.rolling_back:
                self._set_bar(max(0.1, pct / 100), words)
            elif ev.get("stage") == "download":
                self._set_bar(0.06 + pct / 100 * 0.34, words)
            else:
                configuring = raw.startswith(("Preparing to configure", "Configuring", "Installed", "Running"))
                self._step(len(self.step_names) - (1 if configuring else 2))
                self.stage.set_text(self.step_names[self.step_i])
                base = 0.4 if dl else 0.06
                self._set_bar(base + pct / 100 * (1 - base), words)
        elif kind in ("log", "raw"):
            self._log(ev.get("line", ""))
        elif kind == "pmerror":
            self._log(f"dpkg: {ev.get('item', '')}: {ev.get('text', '')}")

    def _on_finished(self, run, status):
        self.busy = False
        if self._inhibit:
            self.app.uninhibit(self._inhibit)
            self._inhibit = 0
        if run.cancelled:
            for child in list(self.actions):
                child.set_sensitive(True)
            self.toast("Установка отменена")
            return
        if self.result and self.result.get("ok"):
            self._success_page()
        elif self.refusal:
            self._problem(errors.refused(*self.refusal))
        elif self.result:
            self._problem(errors.apt_failure(self.result.get("log", ""), self.result.get("rolled_back", False),
                                             self._display_name()))
        else:
            self._problem(errors.Problem("internal", "err", "Установщик завершился с ошибкой", f"Код {status}."))

    # -- results ----------------------------------------------------------------------------------
    def _success_page(self):
        r, d = self.report, self.report.deb
        action = "downgrade" if self.downgrade else r.action
        fetched = [p["name"] for p in r.deps if p["old"] is None]
        sub = f"Версия {d.version}" + (f" · докачано: {', '.join(fetched)}" if fetched else "")
        mark = CheckMark(96)
        mark.set_halign(Gtk.Align.CENTER)
        self._show(page(vbox(12, mark, label(f"{self._display_name()} {DONE_TITLE[action]}", "title-1", wrap=True, xalign=0.5),
                             label(sub, "dim-label", wrap=True, xalign=0.5), valign=Gtk.Align.CENTER, vexpand=True)),
                   "Готово")
        desktop_id = os.path.basename(d.desktop.get("path", ""))
        info = Gio.DesktopAppInfo.new(desktop_id) if desktop_id else None
        buttons = [button("Готово", self.close)]
        if info:
            buttons.append(button("Открыть", lambda: self._launch(info), "suggested-action"))
        self._set_actions(None, *buttons)

    def _launch(self, info):
        info.launch([], self.get_display().get_app_launch_context())
        self.close()

    def _problem(self, problem):
        extra_start = None
        if problem.kind == "threat":
            extra_start = button("Удалить файл", self._trash, "flat", "destructive")
        self._show(problem_page(problem), problem.title if problem.kind == "threat" else "Установка не выполнена")
        copy_label = "Скопировать отчёт" if problem.kind == "threat" else "Скопировать ошибку"
        end = [button(copy_label, lambda: (self.get_clipboard().set(problem.raw), self.toast("Скопировано")))] \
            if problem.raw else []
        self._set_actions(extra_start, *end, button("Закрыть", self.close, "suggested-action"))

    def _trash(self):
        try:
            Gio.File.new_for_path(self.path).trash(None)
            self.toast("Файл перемещён в корзину")
        except GLib.Error as e:
            self.toast(f"Не удалось удалить файл: {e.message}")
