"""Reading a .deb without running or extracting anything from it."""
import hashlib
import io
import os
import posixpath
import subprocess
import tarfile
from dataclasses import dataclass, field

ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"}
SCRIPTS = ("preinst", "postinst", "prerm", "postrm", "config")
MAX_CONTROL = 16 << 20
MAX_ICON = 1 << 20
ICON_ROOTS = ("/usr/share/icons/hicolor/", "/usr/share/pixmaps/")


class DebError(Exception):
    """The file is not a readable Debian package."""

    def __init__(self, kind, detail=""):
        super().__init__(detail or kind)
        self.kind, self.detail = kind, detail


@dataclass
class Entry:
    path: str
    mode: int
    size: int
    kind: str  # file, dir, link, other
    link: str = ""
    elf: bool = False
    packed: bool = False


@dataclass
class DebFile:
    path: str
    size: int
    sha256: str = ""
    fields: dict = field(default_factory=dict)
    scripts: dict = field(default_factory=dict)
    members: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    desktop: dict = field(default_factory=dict)
    icon: bytes | None = None

    @property
    def name(self):
        return self.fields.get("Package", "")

    @property
    def version(self):
        return self.fields.get("Version", "")

    @property
    def arch(self):
        return self.fields.get("Architecture", "")

    @property
    def summary(self):
        return self.fields.get("Description", "").split("\n", 1)[0].strip()


def _run(cmd):
    return subprocess.run(cmd, env=ENV, stdin=subprocess.DEVNULL, capture_output=True)


def parse_fields(text):
    fields, key = {}, None
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[key] += "\n" + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            fields[key] = value.strip()
    return fields


def read_fields(path):
    r = _run(["dpkg-deb", "-f", path])
    if r.returncode != 0:
        raise DebError("not-deb", r.stderr.decode(errors="replace").strip())
    return parse_fields(r.stdout.decode(errors="replace"))


def read_control(path):
    """Maintainer scripts as text plus the control member names. Nothing is executed."""
    r = _run(["dpkg-deb", "--ctrl-tarfile", path])
    if r.returncode != 0 or len(r.stdout) > MAX_CONTROL:
        raise DebError("corrupt", r.stderr.decode(errors="replace").strip())
    scripts, members = {}, []
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as tar:
        for m in tar:
            name = posixpath.basename(m.name)
            if not m.isfile() or not name:
                continue
            members.append(name)
            if name in SCRIPTS or name == "templates":
                scripts[name] = tar.extractfile(m).read(1 << 20).decode("utf-8", "replace")
    return scripts, members


def sha256(path, progress=None):
    h, done, total = hashlib.sha256(), 0, os.path.getsize(path)
    with open(path, "rb") as f:
        while chunk := f.read(4 << 20):
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return h.hexdigest()


def walk_data(path, progress=None):
    """Stream the data archive once: proves it is complete and lists every file.

    Returns (entries, desktop files {path: text}, icon candidates {path: bytes}).
    """
    with subprocess.Popen(["dpkg-deb", "--fsys-tarfile", path], env=ENV, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        return _walk(proc, progress)


def _walk(proc, progress):
    entries, desktops, icons = [], {}, {}
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for m in tar:
                p = "/" + m.name.lstrip("./")
                kind = "file" if m.isfile() else "dir" if m.isdir() else "link" if m.issym() or m.islnk() else "other"
                e = Entry(p, m.mode, m.size, kind, m.linkname)
                if kind == "file" and m.size:
                    data = tar.extractfile(m)
                    head = data.read(4096)
                    e.elf = head.startswith(b"\x7fELF")
                    e.packed = e.elf and b"UPX!" in head
                    small = m.size <= MAX_ICON
                    if small and p.startswith("/usr/share/applications/") and p.endswith(".desktop"):
                        desktops[p] = (head + data.read()).decode("utf-8", "replace")
                    elif small and p.startswith(ICON_ROOTS) and p.endswith((".png", ".svg")):
                        icons[p] = head + data.read()
                    elif small and p.endswith(".png") and ("logo" in p.lower() or "icon" in p.lower()) \
                            and sum(1 for k in icons if k.startswith("logo:")) < 30:
                        icons["logo:" + p] = head + data.read()  # apps that install their icon from a script
                entries.append(e)
                if progress and len(entries) % 50 == 0:
                    progress(len(entries))
    except (tarfile.TarError, EOFError, OSError) as e:
        proc.kill()
        proc.wait()
        raise DebError("corrupt", str(e)) from e
    err = proc.stderr.read().decode(errors="replace").strip()
    if proc.wait() != 0:
        raise DebError("corrupt", err)
    return entries, desktops, icons


def _desktop_entry(text):
    values, in_main = {}, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_main = line == "[Desktop Entry]"
        elif in_main and "=" in line:
            k, _, v = line.partition("=")
            values.setdefault(k.strip(), v.strip())
    return values


def _pick_logo(icons):
    logos = {p: d for p, d in icons.items() if p.startswith("logo:")}
    if not logos:
        return None
    return max(logos.items(), key=lambda kv: ("256" in kv[0], len(kv[1])))[1]


def _pick_icon(name, icons):
    if not name:
        return None
    if name.startswith("/"):
        return icons.get(name)
    best, best_score = None, -1
    for p, data in icons.items():
        if p.startswith("logo:"):
            continue
        stem = posixpath.splitext(posixpath.basename(p))[0]
        if stem != name:
            continue
        score = 10000 if p.endswith(".svg") else 0
        for part in p.split("/"):
            if "x" in part and part.split("x")[0].isdigit():
                score += int(part.split("x")[0])
        if score > best_score:
            best, best_score = data, score
    return best


def open_deb(path, on_hash=None, on_files=None):
    """Everything the installer needs to know about a file, or DebError."""
    deb = DebFile(path=os.path.abspath(path), size=os.path.getsize(path))
    deb.fields = read_fields(deb.path)
    deb.scripts, deb.members = read_control(deb.path)
    deb.sha256 = sha256(deb.path, on_hash)
    deb.entries, desktops, icons = walk_data(deb.path, on_files)
    for p in sorted(desktops):
        entry = _desktop_entry(desktops[p])
        if entry.get("NoDisplay", "").lower() != "true" and entry.get("Type") == "Application":
            deb.desktop = {"path": p, **entry}
            break
    deb.icon = _pick_icon(deb.desktop.get("Icon", deb.name), icons) or _pick_logo(icons)
    return deb
