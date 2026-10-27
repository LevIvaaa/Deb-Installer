"""Runs the root helper through pkexec and turns its JSON lines into GObject signals."""
import json

from gi.repository import Gio, GLib, GObject

from . import HELPER

PKEXEC = "/usr/bin/pkexec"
AUTH_CANCELLED = (126, 127)  # dismissed dialog, wrong password or no polkit agent


class HelperRun(GObject.Object):
    __gsignals__ = {
        "event": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, args, stdin_path=None):
        super().__init__()
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        if stdin_path:
            flags |= Gio.SubprocessFlags.STDIN_PIPE
        self._eof, self._status, self.saw_event = False, None, False
        self.proc = Gio.Subprocess.new([PKEXEC, HELPER, *args], flags)
        if stdin_path:
            # The helper re-hashes what it receives, so a file swapped after review is refused.
            source = Gio.File.new_for_path(stdin_path).read(None)
            self.proc.get_stdin_pipe().splice_async(
                source, Gio.OutputStreamSpliceFlags.CLOSE_SOURCE | Gio.OutputStreamSpliceFlags.CLOSE_TARGET,
                GLib.PRIORITY_DEFAULT, None, self._spliced)
        self._lines = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self._read()
        self.proc.wait_async(None, self._waited)

    @staticmethod
    def install(path, sha256, size, reinstall=False, downgrade=False):
        args = ["install", "--sha256", sha256, "--size", str(size)]
        args += ["--reinstall"] if reinstall else []
        args += ["--allow-downgrade"] if downgrade else []
        return HelperRun(args, stdin_path=path)

    @staticmethod
    def remove(package, expect, purge=False):
        return HelperRun(["remove", "--package", package, "--expect", ",".join(expect)] + (["--purge"] if purge else []))

    def _spliced(self, stream, result):
        try:
            stream.splice_finish(result)
        except GLib.Error:
            pass  # pkexec exited before reading everything: authentication was cancelled

    def _read(self):
        self._lines.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, result):
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            self._eof = True
            self._maybe_finish()
            return
        try:
            event = json.loads(line)
        except ValueError:
            event = {"t": "raw", "line": line}
        if event.get("t") != "raw":
            self.saw_event = True
        self.emit("event", event)
        self._read()

    def _waited(self, proc, result):
        try:
            proc.wait_finish(result)
            self._status = proc.get_exit_status() if proc.get_if_exited() else 128
        except GLib.Error:
            self._status = 128
        self._maybe_finish()

    def _maybe_finish(self):
        if self._eof and self._status is not None:
            self.emit("finished", self._status)

    @property
    def cancelled(self):
        return self._status in AUTH_CANCELLED and not self.saw_event
