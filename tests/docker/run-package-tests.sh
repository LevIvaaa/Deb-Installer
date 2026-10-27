#!/bin/bash
# Installs the built package into a clean ubuntu:26.10 container and exercises it as installed:
#   docker run --rm -v "$PWD":/opt/t:ro ubuntu:26.10 bash /opt/t/tests/docker/run-package-tests.sh
set -u
export DEBIAN_FRONTEND=noninteractive
pass=0 fail=0
ok() {
    if [ "$1" = "$2" ]; then echo "PASS  $3"; pass=$((pass + 1))
    else echo "FAIL  $3: got '$1', want '$2'"; fail=$((fail + 1)); fi
}

apt-get update -qq
apt-get install -y -qq /opt/t/build/deb-installer_*_all.deb > /tmp/install.log 2>&1
ok "$?" 0 "package installs on a clean system with all dependencies"
ok "$(dpkg-query -W -f='${db:Status-Status}' deb-installer)" installed "package is registered"

for f in /usr/bin/deb-installer /usr/libexec/deb-installer/helper /usr/share/applications/local.DebInstaller.desktop \
         /usr/share/polkit-1/actions/local.DebInstaller.policy /usr/lib/deb-installer/debinstaller/app.py; do
    ok "$(test -e "$f" && echo yes)" yes "ships $f"
done
ok "$(stat -c %a /usr/libexec/deb-installer/helper)" 755 "helper is root-owned and not writable by users"
ok "$(stat -c %U /usr/libexec/deb-installer/helper)" root "helper owner"

if command -v pkaction > /dev/null; then
    if ! pkaction --action-id local.DebInstaller.install > /dev/null 2>&1; then
        # containers have no system bus: start one and polkitd so polkit really parses the policy
        command -v dbus-daemon > /dev/null || apt-get install -y -qq dbus-daemon > /dev/null 2>&1 \
            || apt-get install -y -qq dbus > /dev/null 2>&1
        mkdir -p /run/dbus && dbus-daemon --system --fork > /dev/null 2>&1
        /usr/lib/polkit-1/polkitd --no-debug > /dev/null 2>&1 &
        for _ in $(seq 20); do pkaction > /dev/null 2>&1 && break; sleep 0.5; done
    fi
    ok "$(pkaction --action-id local.DebInstaller.install --verbose 2>&1 | grep -c 'implicit active:.*auth_admin')" 1 \
        "polkit reads the install action (password every time)"
    ok "$(pkaction --action-id local.DebInstaller.remove > /dev/null 2>&1 && echo yes)" yes "polkit reads the remove action"
fi
grep -q 'MimeType=application/vnd.debian.binary-package' /usr/share/applications/local.DebInstaller.desktop
ok "$?" 0 "desktop entry handles .deb files"

python3 -I -c '
import sys
sys.path.insert(0, "/usr/lib/deb-installer")
from debinstaller import analysis
r = analysis.analyze("/opt/t/build/fixtures/dci-ok.deb", lambda *a: None)
print(r.problem is None and [d["name"] for d in r.deps] == ["hello"])' > /tmp/analysis.out 2>&1
ok "$(tail -1 /tmp/analysis.out)" True "installed analyser works without a display"

f=/opt/t/build/fixtures/dci-ok.deb
/usr/libexec/deb-installer/helper install --sha256 "$(sha256sum "$f" | cut -c1-64)" --size "$(stat -c %s "$f")" < "$f" > /tmp/helper.out 2>&1
ok "$?" 0 "installed helper installs a package from stdin"
ok "$(dpkg-query -W -f='${db:Status-Status}' dci-ok)" installed "the package is installed"

apt-get remove -y -qq deb-installer > /dev/null 2>&1
ok "$(test -e /usr/libexec/deb-installer/helper || echo gone)" gone "removing deb-installer removes the helper"

echo "---- $pass passed, $fail failed"
[ "$fail" -eq 0 ]
