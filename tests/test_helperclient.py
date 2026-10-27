"""The window <-> helper protocol: file over stdin, JSON events, exit status, cancelled password dialog.

pkexec is replaced by a stub that runs the real helper as root in a throwaway ubuntu:26.10 container.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gi.repository import GLib  # noqa: E402

from debinstaller import helperclient  # noqa: E402

FIX = os.path.join(ROOT, "build", "fixtures")
DOCKER_PKEXEC = """#!/bin/bash
shift  # the helper path pkexec would run; the stub runs the source tree helper instead
exec docker run --rm -i -v "{root}":/opt/t:ro ubuntu:26.10 bash -c \\
  'apt-get update -qq < /dev/null > /dev/null && apt-get install -y -qq python3 < /dev/null > /dev/null 2>&1 \\
   && exec python3 -I /opt/t/helper/deb-installer-helper "$@"' helper "$@"
"""


def run_helper(stub_body, start):
    stub_dir = tempfile.mkdtemp()
    stub = os.path.join(stub_dir, "pkexec")
    with open(stub, "w") as f:
        f.write(stub_body)
    os.chmod(stub, 0o755)
    old, helperclient.PKEXEC = helperclient.PKEXEC, stub
    events, result, loop = [], {}, GLib.MainLoop()
    try:
        run = start()
        run.connect("event", lambda _r, ev: events.append(ev))
        run.connect("finished", lambda r, status: (result.update(status=status, cancelled=r.cancelled), loop.quit()))
        GLib.timeout_add_seconds(300, loop.quit)
        loop.run()
    finally:
        helperclient.PKEXEC = old
        shutil.rmtree(stub_dir)
    return events, result


class Protocol(unittest.TestCase):
    def test_cancelled_password_dialog(self):
        events, result = run_helper("#!/bin/sh\nexit 126\n", lambda: helperclient.HelperRun.remove("x", ["x"]))
        self.assertEqual(result, {"status": 126, "cancelled": True})
        self.assertEqual(events, [])

    @unittest.skipUnless(shutil.which("docker"), "docker is not available")
    def test_install_streams_file_and_events(self):
        path = os.path.join(FIX, "dci-ok.deb")
        if not os.path.exists(path):
            subprocess.run(["bash", os.path.join(ROOT, "tests", "fixtures", "build.sh"), FIX], check=True,
                           capture_output=True)
        sha = subprocess.run(["sha256sum", path], capture_output=True, text=True).stdout[:64]
        events, result = run_helper(DOCKER_PKEXEC.format(root=ROOT),
                                    lambda: helperclient.HelperRun.install(path, sha, os.path.getsize(path)))
        kinds = [e["t"] for e in events]
        self.assertEqual(result["status"], 0, events[-5:])
        self.assertFalse(result["cancelled"])
        self.assertIn("verified", kinds)
        self.assertIn("progress", kinds)
        self.assertEqual(events[-1], {"t": "done", "ok": True})


if __name__ == "__main__":
    unittest.main()
