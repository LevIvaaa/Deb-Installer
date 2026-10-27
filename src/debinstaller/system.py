"""Read-only questions to dpkg and APT, asked as the current user."""
import glob
import mmap
import os
import re
import subprocess
from dataclasses import dataclass, field

import apt_pkg

apt_pkg.init_system()

ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"}
LISTS = "/var/lib/apt/lists"
# Same list as the helper: the window hides what the helper would refuse anyway.
PROTECTED = re.compile(
    r"^(apt|dpkg|libc6|libc-bin|base-files|base-passwd|bash|coreutils|rust-coreutils|gnu-coreutils"
    r"|init|init-system-helpers|systemd|systemd-sysv|udev|sudo|sudo-rs|polkitd|pkexec|login|passwd"
    r"|gdm3|gnome-shell|mutter|network-manager|grub.*|shim.*|linux-(image|headers|modules|generic).*"
    r"|ubuntu-(desktop|desktop-minimal|minimal|standard|server)|deb-installer)(:[a-z0-9]+)?$")
VENDORS = {
    "dl.google.com": "Google", "packages.microsoft.com": "Microsoft", "repo.steampowered.com": "Valve",
    "repo.yandex.ru": "Яндекс", "downloads.claude.ai": "Anthropic", "download.docker.com": "Docker",
    "pkgs.tailscale.com": "Tailscale", "ppa.launchpadcontent.net": "PPA",
}
INSTALLED_STATES = {"installed", "half-configured", "unpacked", "half-installed", "triggers-awaited", "triggers-pending"}


def run(cmd):
    return subprocess.run(cmd, env=ENV, stdin=subprocess.DEVNULL, capture_output=True, text=True)


def vendor(host):
    if not host:
        return ""
    if host.endswith("ubuntu.com"):
        return "Ubuntu"
    return VENDORS.get(host, host)


def archs():
    native = run(["dpkg", "--print-architecture"]).stdout.strip()
    foreign = run(["dpkg", "--print-foreign-architectures"]).stdout.split()
    return native, {"all", native, *foreign}


def installed(name):
    """Installed version of a package, or None."""
    r = run(["dpkg-query", "-W", "-f=${db:Status-Status}\t${Version}", name])
    status, _, version = r.stdout.partition("\t")
    return version if r.returncode == 0 and status in INSTALLED_STATES else None


def compare(a, b):
    return apt_pkg.version_compare(a, b)


def is_protected(name):
    if PROTECTED.match(name):
        return True
    r = run(["dpkg-query", "-W", "-f=${Essential}\t${Priority}", name])
    essential, _, priority = r.stdout.partition("\t")
    return r.returncode == 0 and (essential == "yes" or priority in ("required", "important"))


@dataclass
class Sim:
    rc: int
    installs: list = field(default_factory=list)  # dicts: name, old, new, origin
    removes: list = field(default_factory=list)
    missing: list = field(default_factory=list)  # (dependency, reason)
    output: str = ""

    @property
    def ok(self):
        return self.rc == 0 and not self.removes


def parse_sim(rc, text):
    sim, section = Sim(rc=rc, output=text.strip()), None
    for line in text.splitlines():
        m = re.match(r"^Inst (\S+) (?:\[(\S+)\] )?\((\S+) ([^\[]*?)\s*\[", line)
        if m:
            sim.installs.append({"name": m.group(1), "old": m.group(2), "new": m.group(3), "origin": m.group(4)})
            continue
        if line.startswith(("Remv ", "Purg ")):
            sim.removes.append(line.split()[1])
            continue
        if line.startswith("The following packages will be REMOVED"):
            section = "removed"
            continue
        if line.startswith("The following packages have unmet dependencies"):
            section = "unmet"
            continue
        if section == "removed" and line.startswith(" "):
            sim.removes.extend(n.rstrip("*") for n in line.split())
            continue
        if section == "unmet":
            m = re.search(r"(?:Pre-)?Depends: (.+?) but (.+)$", line)
            if m:
                sim.missing.append((m.group(1).strip(), m.group(2).strip()))
                continue
        if not line.startswith(" "):
            section = None
    sim.removes = list(dict.fromkeys(sim.removes))
    return sim


def simulate_install(path, reinstall=False, downgrade=False):
    extra = (["--reinstall"] if reinstall else []) + (["--allow-downgrades"] if downgrade else [])
    r = run(["apt-get", "-s", "-q", "-o", "APT::Color=0", "--no-remove", *extra, "install", os.path.abspath(path)])
    return parse_sim(r.returncode, r.stdout + r.stderr)


def simulate_remove(name, purge=False):
    r = run(["apt-get", "-s", "-q", "-o", "APT::Color=0", *(["--purge"] if purge else []), "remove", name])
    return parse_sim(r.returncode, r.stdout + r.stderr)


def _stanzas(mm, needle):
    pos = 0 if mm[:len(needle) - 1] == needle[1:] else mm.find(needle)
    while pos != -1:
        start = pos if pos == 0 else pos + 1
        end = mm.find(b"\n\n", start)
        chunk = mm[start:end if end != -1 else len(mm)].decode("utf-8", "replace")
        yield {k: v.strip() for k, _, v in (ln.partition(":") for ln in chunk.splitlines() if ln[:1] != " ")}
        pos = mm.find(needle, start + 1)


def signed_lookup(name, version, arch, sha):
    """Compare the file with the signed APT indexes. APT keeps only indexes whose signature it verified.

    Returns (status, host): status is "verified", "mismatch", "other-version" or "unknown".
    """
    needle = b"\nPackage: " + name.encode() + b"\n"
    status, host = "unknown", None
    for path in glob.glob(f"{LISTS}/*_Packages"):
        try:
            with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                for st in _stanzas(mm, needle):
                    if st.get("Architecture") not in (arch, "all"):
                        continue
                    h = os.path.basename(path).split("_", 1)[0]
                    if st.get("Version") != version:
                        if status == "unknown":
                            status, host = "other-version", h
                        continue
                    if st.get("SHA256") == sha:
                        return "verified", h
                    status, host = "mismatch", h
        except (OSError, ValueError):
            continue
    return status, host


def update_hosts(names):
    """{package: host of a configured repository that ships it} for the given packages."""
    if not names:
        return {}
    r = run(["apt-cache", "policy", *names])
    hosts, current = {}, None
    for line in r.stdout.splitlines():
        if line and not line[0].isspace() and line.endswith(":"):
            current = line[:-1].split(":")[0]
            continue
        m = re.match(r"^\s+\d+ (https?)://([^/\s]+)", line)
        if current and m and current not in hosts:
            hosts[current] = m.group(2)
    return hosts


def summaries(names):
    if not names:
        return {}
    r = run(["dpkg-query", "-W", "-f=${Package}\t${binary:Summary}\n", *names])
    return dict(line.split("\t", 1) for line in r.stdout.splitlines() if "\t" in line)


@dataclass
class App:
    name: str
    package: str
    version: str
    size_kb: int
    desktop: str
    host: str | None


def third_party_apps():
    """Installed packages with a visible menu entry that did not come from the Ubuntu archive."""
    from gi.repository import Gio

    owned = {}
    for lst in glob.glob("/var/lib/dpkg/info/*.list"):
        pkg = os.path.basename(lst)[:-5].split(":")[0]
        try:
            with open(lst, encoding="utf-8", errors="replace") as f:
                for line in f:
                    p = line.rstrip("\n")
                    if p.startswith("/usr/share/applications/") and p.endswith(".desktop") and p.count("/") == 4:
                        owned.setdefault(pkg, []).append(p)
        except OSError:
            continue
    hosts = update_hosts(sorted(owned))
    candidates = {pkg: paths for pkg, paths in owned.items() if not (hosts.get(pkg) or "").endswith("ubuntu.com")}
    if not candidates:
        return []
    r = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Installed-Size}\t${db:Status-Status}\n", *candidates])
    meta = {}
    for line in r.stdout.splitlines():
        pkg, version, size, status = (line.split("\t") + ["", "", ""])[:4]
        if status == "installed":
            meta[pkg] = (version, int(size or 0))
    apps = []
    for pkg, paths in candidates.items():
        if pkg not in meta or PROTECTED.match(pkg):
            continue
        for p in sorted(paths):
            info = Gio.DesktopAppInfo.new_from_filename(p)
            if info and info.should_show():
                apps.append(App(info.get_name(), pkg, meta[pkg][0], meta[pkg][1], p, hosts.get(pkg)))
                break
    return sorted(apps, key=lambda a: a.size_kb, reverse=True)
