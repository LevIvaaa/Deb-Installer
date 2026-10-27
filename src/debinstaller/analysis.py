"""Everything the window shows before Install, computed in a worker thread as the current user."""
import os
from dataclasses import dataclass, field

from . import audit, debfile, errors, system, text

PKG_ROWS = ("Целостность", "Архитектура", "Зависимости", "Системные пакеты")
SEC_ROWS = ("Подлинность", "Скрипты установки", "Файлы пакета")


@dataclass
class Report:
    path: str
    size: int
    deb: debfile.DebFile | None = None
    installed: str | None = None
    action: str = "install"  # install, reinstall, upgrade, downgrade
    sim: system.Sim | None = None
    deps: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    auth: tuple = ("unknown", None)
    update_host: str | None = None
    sec: list = field(default_factory=list)  # (state, text) per SEC_ROWS
    verdict: tuple = ("ok", "", "")
    problem: errors.Problem | None = None

    @property
    def blocked(self):
        return self.problem is not None


def _group_state(found, ok_text):
    for sev, state in (("critical", "fail"), ("warn", "warn")):
        hits = [f for f in found if f.severity == sev]
        if hits:
            return state, hits[0].title if len(hits) == 1 else f"{hits[0].title} и ещё {len(hits) - 1}"
    return "ok", ok_text


def analyze(path, emit):
    """emit(group, row, state, text) reports each row as it runs: group is "pkg" or "sec"."""
    r = Report(path=os.path.abspath(path), size=os.path.getsize(path))

    emit("pkg", 0, "run", "Чтение архива…")
    try:
        deb = debfile.open_deb(
            path,
            on_hash=lambda done, total: emit("pkg", 0, "run", f"Отпечаток: {done * 100 // max(total, 1)} %"),
            on_files=lambda n: emit("pkg", 0, "run", f"Файлы: {text.number(n)}"))
    except (debfile.DebError, OSError) as e:
        err = e if isinstance(e, debfile.DebError) else debfile.DebError("corrupt", str(e))
        emit("pkg", 0, "fail", "Не deb-пакет" if err.kind == "not-deb" else "Архив повреждён")
        r.problem = errors.broken(path, r.size, err)
        return r
    r.deb = deb
    emit("pkg", 0, "ok", f"Архив цел · {text.size(r.size)}")

    native, allowed = system.archs()
    if deb.arch not in allowed:
        emit("pkg", 1, "fail", deb.arch)
        r.problem = errors.arch(deb, native)
        return r
    emit("pkg", 1, "ok", deb.arch)

    r.installed = system.installed(deb.name)
    if r.installed:
        c = system.compare(deb.version, r.installed)
        r.action = "reinstall" if c == 0 else "upgrade" if c > 0 else "downgrade"

    emit("pkg", 2, "run", "Проверка…")
    sim = r.sim = system.simulate_install(path, reinstall=r.action == "reinstall", downgrade=r.action == "downgrade")
    if sim.removes:
        emit("pkg", 2, "ok", "Подобраны")
        emit("pkg", 3, "fail", f"{text.packages(len(sim.removes))} под удаление")
        r.problem = errors.conflict(deb, sim)
        return r
    if sim.rc != 0:
        emit("pkg", 2, "fail", f"{len(sim.missing) or 'Часть'} не найдены")
        r.problem = errors.deps(deb, sim)
        return r
    r.deps = [i for i in sim.installs if i["name"].split(":")[0] != deb.name]
    fetch = [i for i in r.deps if i["old"] is None]
    emit("pkg", 2, "ok", f"{len(fetch)} докачается из репозиториев" if fetch else "Все установлены")
    if system.is_protected(deb.name):
        emit("pkg", 3, "fail", "Подменяет системный пакет")
        r.problem = errors.protected(deb)
        return r
    emit("pkg", 3, "ok", "Не затрагиваются")

    emit("sec", 0, "run", "Сверка с репозиторием…")
    status, host = r.auth = system.signed_lookup(deb.name, deb.version, deb.arch, deb.sha256)
    who = system.vendor(host)
    auth = {
        "verified": ("ok", f"Совпадает с публикацией {who}"),
        "mismatch": ("fail", f"Отличается от публикации {who}"),
        "other-version": ("warn", f"Не проверена: этой версии уже нет в репозитории {who}"),
        "unknown": ("warn", "Не проверена: репозиторий производителя не подключён"),
    }[status]
    emit("sec", 0, *auth)

    emit("sec", 1, "run", "Анализ скриптов…")
    r.findings = audit.audit(deb.scripts, deb.entries)
    scripts = _group_state([f for f in r.findings if f.area == "scripts"], "Опасного нет")
    emit("sec", 1, *scripts)
    emit("sec", 2, "run", "Анализ файлов…")
    n_files = sum(1 for e in deb.entries if e.kind == "file")
    files = _group_state([f for f in r.findings if f.area == "files"], f"{text.files(n_files)}, опасного нет")
    emit("sec", 2, *files)
    r.sec = [auth, scripts, files]

    r.update_host = system.update_hosts([deb.name]).get(deb.name) or (host if status == "verified" else None)
    if status == "mismatch" or any(f.severity == "critical" for f in r.findings):
        r.verdict = ("bad", "Опасный пакет", "Установка заблокирована")
        r.problem = errors.threat(deb, r.findings, r.auth)
    elif status != "verified":
        r.verdict = ("warn", "Есть замечания", "Подлинность не проверена")
    else:  # notes on scripts and files stay visible on their own rows
        r.verdict = ("ok", "Проверка пройдена", f"Подлинный файл {who}")
    return r
