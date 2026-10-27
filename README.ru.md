# Установщик пакетов

[English](README.md)

Приложение для Ubuntu 26.10 (GTK 4 + libadwaita). Двойной щелчок по `.deb` открывает окно с проверкой пакета и кнопкой «Установить». Значок в меню приложений открывает список программ, которые поставлены не из Ubuntu, с удалением.

## Как устроено

| Часть | Где | Права |
|---|---|---|
| Окно и проверки | `/usr/lib/deb-installer/debinstaller/` | пользователь |
| Помощник | `/usr/libexec/deb-installer/helper` | root, только через `pkexec` |
| Правила polkit | `/usr/share/polkit-1/actions/local.DebInstaller.policy` | пароль при каждой операции |

Окно проверяет пакет от вашего пользователя:
- целостность (архив читается целиком);
- архитектура;
- зависимости и удаления (`apt-get -s --no-remove`);
- подлинность: отпечаток сверяется с подписанными индексами APT;
- скрипты и файлы пакета.

Опасные находки блокируют установку.

Помощнику не передаются пути и параметры apt. Файл приходит через stdin и сверяется с отпечатком, который вы видели. Установка идёт через `apt-get --no-remove`. Если скрипт пакета упал, помощник откатывает пакет и зависимости, поставленные в той же операции. Удаление выполняется, только если набор пакетов совпадает с подтверждённым.

## Сборка и тесты

```
bash build-deb.sh                                   # build/deb-installer_1.0_all.deb
python3 -I -m unittest discover -s tests -p 'test_*.py'
docker run --rm -v "$PWD":/opt/t:ro ubuntu:26.10 bash /opt/t/tests/docker/run-helper-tests.sh
docker run --rm -v "$PWD":/opt/t:ro ubuntu:26.10 bash /opt/t/tests/docker/run-package-tests.sh
```

## Установка

```
sudo apt install ./build/deb-installer_1.0_all.deb
gio mime application/vnd.debian.binary-package local.DebInstaller.desktop
```

## Как вернуть как было

```
gio mime application/vnd.debian.binary-package snap-store_snap-store.desktop
sudo apt remove deb-installer
```
