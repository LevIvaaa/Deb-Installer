# Deb Installer

[Русская версия](README.ru.md)

A double-click installer for `.deb` packages on Ubuntu 26.10 (GTK 4 + libadwaita). Opening a `.deb` shows a window that checks the package and offers an **Install** button. The app icon in the menu opens a list of programs installed from outside Ubuntu, with removal.

## How it works

| Part | Where | Runs as |
|---|---|---|
| Window and checks | `/usr/lib/deb-installer/debinstaller/` | the user |
| Helper | `/usr/libexec/deb-installer/helper` | root, only through `pkexec` |
| polkit rules | `/usr/share/polkit-1/actions/local.DebInstaller.policy` | password for every operation |

The window checks the package as your user:
- integrity (the whole archive is readable);
- architecture;
- dependencies and removals (`apt-get -s --no-remove`);
- authenticity: the fingerprint is matched against signed APT indexes;
- the package's scripts and files.

Dangerous findings block the installation.

The helper never receives paths or apt options. The file arrives on stdin and is checked against the fingerprint you saw. Installation goes through `apt-get --no-remove`. If a package script fails, the helper rolls back the package and the dependencies installed in the same operation. Removal only runs if the set of packages matches the one you confirmed.

## Build and test

```
bash build-deb.sh                                   # build/deb-installer_1.0_all.deb
python3 -I -m unittest discover -s tests -p 'test_*.py'
docker run --rm -v "$PWD":/opt/t:ro ubuntu:26.10 bash /opt/t/tests/docker/run-helper-tests.sh
docker run --rm -v "$PWD":/opt/t:ro ubuntu:26.10 bash /opt/t/tests/docker/run-package-tests.sh
```

## Install

```
sudo apt install ./build/deb-installer_1.0_all.deb
gio mime application/vnd.debian.binary-package local.DebInstaller.desktop
```

## Undo

```
gio mime application/vnd.debian.binary-package snap-store_snap-store.desktop
sudo apt remove deb-installer
```
