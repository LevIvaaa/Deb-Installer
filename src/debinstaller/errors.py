"""Problems the window shows instead of the Install button, and failures reported by the helper."""
import os
import re
from dataclasses import dataclass, field

from . import system, text

HINTS = {
    "libssl1.1": "Заменена на libssl3",
    "libssl1.0.0": "Заменена на libssl3",
    "libwebkit2gtk-4.0-37": "Есть только версия 4.1",
    "libjavascriptcoregtk-4.0-18": "Есть только версия 4.1",
    "libappindicator1": "Заменена на libayatana-appindicator",
    "libappindicator3-1": "Заменена на libayatana-appindicator3-1",
    "libgconf-2-4": "Удалена из Ubuntu",
    "libcurl3": "Заменена на libcurl4",
    "libffi6": "Заменена на libffi8",
    "python2": "Python 2 удалён из Ubuntu",
    "python": "Python 2 удалён из Ubuntu",
    "libpython2.7": "Python 2 удалён из Ubuntu",
}


@dataclass
class Problem:
    kind: str
    icon: str  # err, shield, broken, virus
    title: str
    text: str = ""
    head: str = ""
    items: list = field(default_factory=list)  # (title, subtitle)
    raw_title: str = ""
    raw: str = ""
    advice: tuple | None = None
    rolled_back: bool = False


def broken(path, size, err):
    name = os.path.basename(path)
    if err.kind == "not-deb":
        return Problem("broken", "broken", "Это не deb-пакет", f"{name} · {text.size(size)}. Скачайте файл заново.",
                       raw_title="Текст ошибки dpkg-deb", raw=err.detail)
    return Problem("broken", "broken", "Файл повреждён", f"{name} · {text.size(size)}. Скорее всего, загрузка оборвалась.",
                   raw_title="Текст ошибки dpkg-deb", raw=err.detail)


def arch(deb, native):
    return Problem("arch", "err", "Пакет для другого компьютера",
                   f"{deb.name} собран для {deb.arch}, а эта система {native}.")


def deps(deb, sim):
    items, old = [], False
    for dep, why in sim.missing:
        name = dep.split()[0]
        hint = HINTS.get(name)
        old = old or hint is not None
        items.append((name, hint or ("Нет в подключённых репозиториях" if "not installable" in why else why)))
    if not items:
        items = [("APT не смог подобрать зависимости", "")]
    lead = f"{deb.name} {deb.version} собран для старой версии Ubuntu." if old else \
        f"{deb.name} {deb.version} требует пакеты, которых нет в подключённых репозиториях."
    return Problem("deps", "err", "Не хватает библиотек", lead, "Чего не хватает", items,
                   "Текст ошибки APT", _apt_excerpt(sim.output),
                   advice=("Решение", "Версия для Ubuntu 24.04 и новее, snap или Flatpak" if old
                           else "Подключите репозиторий производителя или найдите другую сборку"))


def conflict(deb, sim):
    about = system.summaries(sim.removes)
    items = [(n, about.get(n, "")) for n in sim.removes]
    return Problem("conflict", "shield", "Пакет удалил бы часть системы",
                   f"Для установки {deb.name} пришлось бы удалить {text.packages(len(items))}.",
                   "Пришлось бы удалить", items, "Вывод симуляции APT", _apt_excerpt(sim.output))


def protected(deb):
    return Problem("protected", "shield", "Пакет подменяет системный компонент",
                   f"Файл выдаёт себя за {deb.name}. Системные пакеты из файлов не ставятся.")


def threat(deb, findings, auth):
    items = [(f.title, f.detail) for f in findings if f.severity == "critical"]
    status, host = auth
    if status == "mismatch":
        items.insert(0, ("Файл отличается от опубликованного", f"Репозиторий {host}: та же версия, другой отпечаток"))
    level = {"critical": "КРИТИЧНО", "warn": "внимание"}
    lines = [deb.path.rsplit("/", 1)[-1]] + [f"{level[f.severity]:9} {f.title}: {f.detail}" for f in findings
                                             if f.severity != "info"]
    auth_text = {"verified": "подтверждена", "mismatch": "НЕ СОВПАДАЕТ", "other-version": "версии нет в индексе",
                 "unknown": "не проверена"}[status]
    lines.append(f"подлинность: {auth_text}" + (f" ({host})" if host else ""))
    return Problem("threat", "virus", "Опасный пакет", deb.path.rsplit("/", 1)[-1], "Что нашли", items,
                   "Отчёт проверки", "\n".join(lines))


NOISE = ("Reading package", "Building dependency", "Reading state", "Solving dep", "NOTE: This is only",
         "      apt-get needs", "      Keep also", "      so don't depend")
# Boilerplate blocks: first line opens the block, second closes it (both dropped).
BLOCKS = (("Some packages could not be installed", "The following information may help"),
          ("The following packages were automatically installed", "Use 'apt autoremove'"))


def _apt_excerpt(output):
    lines, closing = [], None
    for ln in output.splitlines():
        if closing:
            if ln.startswith(closing):
                closing = None
            continue
        opened = next((end for start, end in BLOCKS if ln.startswith(start)), None)
        if opened:
            closing = opened
        elif not ln.startswith(NOISE):
            lines.append(ln)
    return "\n".join(lines).strip()


REFUSED = {
    "sha256": ("Файл изменился после проверки", "Откройте его заново, чтобы проверить ещё раз."),
    "size": ("Файл изменился после проверки", "Откройте его заново, чтобы проверить ещё раз."),
    "space": ("Недостаточно места на диске", "Освободите место и повторите."),
    "invalid": ("Файл повреждён", "Скачайте его заново."),
    "arch": ("Пакет для другого компьютера", ""),
    "protected": ("Пакет подменяет системный компонент", ""),
    "remove": ("Пакет удалил бы часть системы", ""),
    "simulate": ("Не удалось подобрать зависимости", "Состояние системы изменилось после проверки."),
    "changed": ("Набор пакетов изменился", "Обновите список программ и повторите."),
    "args": ("Внутренняя ошибка установщика", ""),
}


def refused(reason, detail):
    title, lead = REFUSED.get(reason, ("Установка отклонена", ""))
    return Problem(f"refused-{reason}", "shield" if reason in ("protected", "remove") else "err", title, lead,
                   raw_title="Подробности", raw=detail)


def apt_failure(log, rolled_back, name):
    m = re.search(r"post-installation script subprocess returned error exit status (\d+)", log)
    if m:
        lead = f"Скрипт настройки пакета завершился с ошибкой (код {m.group(1)})."
    elif m := re.search(r"trying to overwrite '([^']+)', which is also in package (\S+)", log):
        lead = f"Файл {m.group(1)} уже принадлежит пакету {m.group(2)}."
    elif "Could not get lock" in log:
        lead = "Другая установка не закончилась за 5 минут."
    elif "enough free space" in log:
        lead = "Недостаточно места на диске."
    elif "Unable to fetch" in log or "Failed to fetch" in log:
        lead = "Не удалось скачать зависимости: нет сети или репозиторий недоступен."
    else:
        lead = "APT завершился с ошибкой."
    errors = [ln for ln in log.splitlines() if ln.startswith(("E:", "dpkg:", " ")) or "error" in ln.lower()]
    return Problem("apt", "err", f"Не удалось установить {name}", lead, raw_title="Текст ошибки",
                   raw="\n".join(errors[-40:]) or log[-4000:], rolled_back=rolled_back)
