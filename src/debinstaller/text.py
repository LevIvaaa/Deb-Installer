"""Russian number, size and plural formatting, independent of the system locale."""
import re


def plural(n, one, few, many):
    a, b = n % 10, n % 100
    if a == 1 and b != 11:
        return one
    if 2 <= a <= 4 and not 12 <= b <= 14:
        return few
    return many


def number(n):
    return f"{n:,}".replace(",", " ")


def size(n):
    if n < 1000:
        return f"{n} {plural(n, 'байт', 'байта', 'байт')}"
    for unit, div in (("КБ", 1e3), ("МБ", 1e6), ("ГБ", 1e9), ("ТБ", 1e12)):
        v = n / div
        if v < 999.5 or unit == "ТБ":
            s = f"{v:.1f}" if v < 100 else f"{v:.0f}"
            if s.endswith(".0"):
                s = s[:-2]
            return s.replace(".", ",") + " " + unit


def files(n):
    return f"{number(n)} {plural(n, 'файл', 'файла', 'файлов')}"


def packages(n):
    return f"{n} {plural(n, 'пакет', 'пакета', 'пакетов')}"


def packages_genitive(n):
    return f"{n} {plural(n, 'пакета', 'пакетов', 'пакетов')}"


_STATUS = (
    (r"^Retrieving file (\d+) of (\d+)(?: \((.+)\))?", lambda m: f"Файл {m[1]} из {m[2]}" + (f" · {m[3]}" if m[3] else "")),
    (r"^Preparing to unpack (\S+)", lambda m: f"Подготовка: {m[1]}"),
    (r"^Unpacking (\S+)", lambda m: f"Распаковка: {m[1]}"),
    (r"^Preparing to configure (\S+)", lambda m: f"Подготовка к настройке: {m[1]}"),
    (r"^Configuring (\S+)", lambda m: f"Настройка: {m[1]}"),
    (r"^Installed (\S+)", lambda m: f"Установлен: {m[1]}"),
    (r"^Preparing for removal of (\S+)", lambda m: f"Подготовка к удалению: {m[1]}"),
    (r"^Removing (\S+)", lambda m: f"Удаление: {m[1]}"),
    (r"^Removed (\S+)", lambda m: f"Удалён: {m[1]}"),
    (r"^Completely removing (\S+)", lambda m: f"Полное удаление: {m[1]}"),
    (r"^Running post-installation trigger (\S+)", lambda m: f"Триггер: {m[1]}"),
    (r"^Running dpkg", lambda m: "Запуск dpkg"),
)


def apt_status(value):
    """APT's machine-readable status line in Russian; unknown lines pass through unchanged."""
    for rx, fmt in _STATUS:
        m = re.match(rx, value)
        if m:
            return fmt(m)
    return value
