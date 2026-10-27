#!/bin/bash
# Builds build/deb-installer_<version>_all.deb from the source tree.
set -euo pipefail
cd "$(dirname "$0")"
version=$(python3 -I -c 'import sys; sys.path.insert(0, "src"); import debinstaller; print(debinstaller.VERSION)')
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT

install -D -m 0755 data/deb-installer "$root/usr/bin/deb-installer"
install -d "$root/usr/lib/deb-installer/debinstaller"
install -m 0644 src/debinstaller/*.py src/debinstaller/style.css "$root/usr/lib/deb-installer/debinstaller/"
install -D -m 0755 helper/deb-installer-helper "$root/usr/libexec/deb-installer/helper"
install -D -m 0644 data/local.DebInstaller.desktop "$root/usr/share/applications/local.DebInstaller.desktop"
install -D -m 0644 data/local.DebInstaller.policy "$root/usr/share/polkit-1/actions/local.DebInstaller.policy"
install -D -m 0644 data/local.DebInstaller.svg "$root/usr/share/icons/hicolor/scalable/apps/local.DebInstaller.svg"
install -D -m 0644 README.md "$root/usr/share/doc/deb-installer/README.md"

mkdir "$root/DEBIAN"
cat > "$root/DEBIAN/control" <<EOF
Package: deb-installer
Version: $version
Architecture: all
Maintainer: Lev Iva <212107632+LevIvaaa@users.noreply.github.com>
Installed-Size: $(du -sk "$root/usr" | cut -f1)
Depends: python3 (>= 3.12), python3-gi, python3-apt, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.7), pkexec, polkitd, apt (>= 2.4), dpkg
Section: admin
Priority: optional
Description: double-click installer for .deb packages
 Checks a .deb before installing it: integrity, architecture, dependencies,
 authenticity against signed APT repositories, and what its scripts and
 files would do. Installs through APT without removing anything, rolls back
 a failed install, and lists third-party programs for removal.
EOF

mkdir -p build
dpkg-deb --build --root-owner-group "$root" "build/deb-installer_${version}_all.deb" > /dev/null
echo "build/deb-installer_${version}_all.deb"
