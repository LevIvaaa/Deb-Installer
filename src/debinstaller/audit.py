"""What a package does to the system, judged from its scripts and file list.

Severity: "critical" blocks the install, "warn" needs attention, "info" is shown as is.
"""
import posixpath
import re
from dataclasses import dataclass


@dataclass
class Finding:
    severity: str
    area: str  # scripts or files
    title: str
    detail: str = ""


_IP_URL = r"https?://(?!127\.|0\.0\.0\.0)\d{1,3}(?:\.\d{1,3}){3}"
SCRIPT_RULES = [
    ("critical", "Скачивает и запускает код из интернета",
     r"(?:curl|wget)\b[^\n|;&]*\|\s*(?:sudo\s+)?(?:ba|da|z)?sh\b|(?:ba)?sh\s+(?:-c\s+)?[\"']?\$\((?:curl|wget)\b|(?:ba)?sh\s+<\((?:curl|wget)"),
    ("critical", "Запускает закодированный код", r"base64\s+(?:-d|--decode)[^\n]*\|\s*(?:ba)?sh\b|eval\s+[\"']?\$\(\s*echo[^\n]*base64"),
    ("critical", "Добавляет SSH-ключ", r"authorized_keys"),
    ("critical", "Меняет права sudo", r"/etc/sudoers"),
    ("critical", "Меняет вход в систему (PAM)", r"/etc/pam\.d/|pam_exec"),
    ("critical", "Подгружает код во все программы", r"/etc/ld\.so\.preload"),
    ("critical", "Создаёт пользователя с правами root", r"(?:useradd|usermod)\b[^\n]*-u\s*0\b"),
    ("critical", "Отключает защиту системы", r"\bufw\s+disable\b|\bsetenforce\s+0\b|systemctl\s+(?:stop|disable|mask)\s+(?:apparmor|ufw)\b|\biptables\s+-F\b"),
    ("critical", "Стирает следы", r"\bhistory\s+-c\b|unset\s+HISTFILE"),
    ("warn", "Обращается к серверу по IP-адресу", _IP_URL),
    ("warn", "Скачивает файлы при установке", r"\b(?:curl|wget)\b"),
    ("warn", "Добавляет системную службу", r"systemctl\s+(?:--now\s+)?enable\b|deb-systemd-helper\s+enable\b|update-rc\.d\b"),
    ("warn", "Ставит модуль ядра", r"\bdkms\b|\bmodprobe\b|\binsmod\b"),
    ("warn", "Делает файлы неизменяемыми", r"\bchattr\s+\+i\b"),
    ("info", "Подключит репозиторий", r"sources\.list|\.sources\b|/keyrings/|trusted\.gpg|\bapt-key\b"),
    ("info", "Добавит задачу cron", r"/etc/cron|\bcrontab\b"),
    ("info", "Загрузит профиль AppArmor", r"apparmor_parser"),
    ("info", "Создаст системного пользователя", r"\b(?:adduser|useradd)\b"),
]
_COMPILED = [(sev, title, re.compile(rx)) for sev, title, rx in SCRIPT_RULES]

HIDDEN_OK = ("/.build-id/",)
SUSPICIOUS_ROOTS = ("/etc/", "/tmp/", "/var/tmp/", "/dev/", "/root/", "/boot/")


def _first_line(text, rx):
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#!") else ""
        if rx.search(code):
            return n, line.strip()
    return None


def audit_scripts(scripts):
    found, seen = [], set()
    for sev, title, rx in _COMPILED:
        for name in ("preinst", "postinst", "prerm", "postrm", "config"):
            hit = _first_line(scripts.get(name, ""), rx)
            if hit and title not in seen:
                seen.add(title)
                found.append(Finding(sev, "scripts", title, f"{name}:{hit[0]} · {hit[1][:120]}"))
                break
    if "templates" in scripts and "Вопрос при установке" not in seen:
        found.append(Finding("info", "scripts", "Вопрос при установке", "Будет выбран ответ по умолчанию"))
    return found


def audit_files(entries):
    found, seen = [], set()

    def add(sev, title, path):
        if title not in seen:
            seen.add(title)
            found.append(Finding(sev, "files", title, path))

    for e in entries:
        p, base = e.path, posixpath.basename(e.path.rstrip("/"))
        if e.kind == "file" and e.mode & 0o6000 and e.mode & 0o111:
            add("warn", "Файл с правами root (setuid)", p)
        if p.startswith(("/etc/sudoers", "/etc/sudoers.d/")):
            add("critical", "Меняет права sudo", p)
        elif p.startswith("/etc/pam.d/") or p.startswith(("/usr/lib/security/", "/lib/security/")):
            add("critical", "Меняет вход в систему (PAM)", p)
        elif p == "/etc/ld.so.preload":
            add("critical", "Подгружает код во все программы", p)
        elif p.startswith("/root/") and e.kind != "dir":
            add("critical", "Кладёт файлы в домашнюю папку root", p)
        elif base.startswith(".") and e.kind != "dir" and not any(h in p for h in HIDDEN_OK) \
                and p.startswith(("/etc/", "/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/lib/systemd/", "/usr/lib/systemd/")):
            add("critical", "Скрытый файл в системной папке", p)
        elif e.elf and p.startswith(SUSPICIOUS_ROOTS):
            add("critical", "Программа в необычном месте", p)
        elif p.startswith(("/etc/systemd/system/", "/lib/systemd/system/", "/usr/lib/systemd/system/")) and p.endswith(".service"):
            add("warn", "Добавляет системную службу", p)
        elif p.startswith(("/etc/polkit-1/rules.d/", "/usr/share/polkit-1/rules.d/")):
            add("warn", "Меняет правила polkit", p)
        elif p.startswith("/etc/profile.d/"):
            add("warn", "Меняет окружение при входе", p)
        elif p.startswith("/etc/xdg/autostart/"):
            add("warn", "Автозапуск для всех пользователей", p)
        elif p.endswith(".ko") or p.startswith("/lib/modules/") and e.kind == "file":
            add("warn", "Ставит модуль ядра", p)
        elif p.startswith(("/etc/apt/sources.list.d/", "/etc/apt/keyrings/", "/usr/share/keyrings/", "/etc/apt/trusted.gpg.d/")) and e.kind == "file":
            add("info", "Подключит репозиторий", p)
        elif p.startswith("/etc/cron") and e.kind == "file":
            add("info", "Добавит задачу cron", p)
        if e.packed:
            add("warn", "Сжатый исполняемый файл", p)
    return found


def audit(scripts, entries):
    """Script and file findings, the most severe first, one entry per kind of action."""
    found = audit_scripts(scripts)
    titles = {f.title for f in found}
    found += [f for f in audit_files(entries) if f.title not in titles]
    order = {"critical": 0, "warn": 1, "info": 2}
    return sorted(found, key=lambda f: order[f.severity])
