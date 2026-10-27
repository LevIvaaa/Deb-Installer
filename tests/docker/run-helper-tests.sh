#!/bin/bash
# Integration tests for the root helper, run as root inside a throwaway ubuntu:26.10 container:
#   docker run --rm -v "$PWD":/opt/t:ro ubuntu:26.10 bash /opt/t/tests/docker/run-helper-tests.sh
set -u
H=/opt/t/helper/deb-installer-helper
F=/opt/t/build/fixtures
OUT=/tmp/out.jsonl
pass=0 fail=0

ok() {
    if [ "$1" = "$2" ]; then echo "PASS  $3"; pass=$((pass + 1))
    else echo "FAIL  $3: got '$1', want '$2'"; sed 's/^/      /' "$OUT" | tail -5; fail=$((fail + 1)); fi
}
install_deb() { # file [extra helper args]
    local f=$1; shift
    python3 -I "$H" install --sha256 "$(sha256sum "$f" | cut -c1-64)" --size "$(stat -c %s "$f")" "$@" < "$f" > "$OUT" 2>&1
    echo $?
}
reason() {
    python3 -I -c '
import json, sys
for line in open(sys.argv[1]):
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("t") == "refused":
        print(event["reason"])' "$OUT"
}
state() { dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null || echo not-installed; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq python3 > /dev/null

ok "$(install_deb "$F/dci-ok.deb")" 0 "installs a local package and pulls its dependency"
ok "$(state dci-ok)/$(state hello)" "installed/installed" "package and dependency are installed"

f="$F/dci-ok.deb"
python3 -I "$H" install --sha256 "$(printf '0%.0s' $(seq 64))" --size "$(stat -c %s "$f")" < "$f" > "$OUT" 2>&1
ok "$?/$(reason)" "2/sha256" "refuses a file whose fingerprint changed"

ok "$(install_deb "$F/dci-conflict.deb")/$(reason)" "2/remove" "refuses an install that would remove packages"
ok "$(state hello)/$(state dci-ok)" "installed/installed" "nothing was removed"
ok "$(install_deb "$F/dci-arm.deb")/$(reason)" "2/arch" "refuses a foreign architecture"
ok "$(install_deb "$F/fake-dpkg.deb")/$(reason)" "2/protected" "refuses a file that claims to be dpkg"
ok "$(install_deb "$F/dci-missing.deb")/$(reason)" "2/simulate" "refuses unmet dependencies"
ok "$(install_deb "$F/broken-truncated.deb")/$(reason)" "2/invalid" "refuses a truncated archive"
ok "$(install_deb "$F/broken-html.deb")/$(reason)" "2/invalid" "refuses a file that is not a deb"

ok "$(install_deb "$F/dci-failpost.deb")" 3 "reports a failing postinst"
ok "$(state dci-failpost)/$(state figlet)" "not-installed/not-installed" "rolls back the package and the dependency it pulled"
ok "$(dpkg --audit | wc -l)" 0 "dpkg database is consistent after the rollback"

python3 -I "$H" remove --package dci-ok --expect hello > "$OUT" 2>&1
ok "$?/$(reason)" "2/changed" "refuses a removal set that differs from the confirmed one"
python3 -I "$H" remove --package apt --expect apt > "$OUT" 2>&1
ok "$?/$(reason)" "2/protected" "refuses to remove a protected package"
python3 -I "$H" remove --package dci-ok --expect dci-ok > "$OUT" 2>&1
ok "$?" 0 "removes exactly the confirmed package"
ok "$(state dci-ok)/$(state hello)" "not-installed/installed" "leaves the dependency (no autoremove)"

python3 -I "$H" install --sha256 nothex --size 1 < /dev/null > "$OUT" 2>&1
ok "$?/$(reason)" "2/args" "rejects malformed arguments"
ok "$(ls /var/cache/deb-installer | wc -l)" 0 "cleans up its transaction directories"

echo "---- $pass passed, $fail failed"
[ "$fail" -eq 0 ]
