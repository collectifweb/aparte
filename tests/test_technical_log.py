import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from aparte import technical_log


class TechnicalLogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs = self.root / "aparte/logs"

    def test_private_creation_even_with_permissive_umask(self):
        original = os.umask(0)
        try:
            technical_log.write_event("invoked")
        finally:
            os.umask(original)
        self.assertEqual(self.logs.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.logs.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.logs / "hotkey.jsonl").stat().st_mode & 0o777, 0o600)
        event = json.loads((self.logs / "hotkey.jsonl").read_text())
        self.assertEqual(event["event"], "invoked")
        self.assertIn("+00:00", event["utc"])

    def test_rotation_is_bounded_and_keeps_latest_entries(self):
        with mock.patch.object(technical_log, "MAX_BYTES", 1024):
            for _ in range(100):
                technical_log.write_event("failed", error_type="RuntimeError")
        self.assertEqual({p.name for p in self.logs.iterdir()}, {"hotkey.jsonl", "hotkey.jsonl.1"})
        for path in self.logs.iterdir():
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            for line in path.read_text().splitlines():
                self.assertEqual(json.loads(line)["error_type"], "RuntimeError")

    def test_unknown_event_and_generic_diagnostic_are_not_written(self):
        technical_log.write_event("secret dictated text")
        self.assertFalse(self.logs.exists())
        technical_log.write_event("failed", audio_diagnostic="secret dictated text")
        self.assertNotIn("secret", (self.logs / "hotkey.jsonl").read_text())

    def test_disk_failure_is_best_effort(self):
        with mock.patch.object(technical_log, "_directory", side_effect=OSError("full")):
            technical_log.write_event("invoked")

    def test_symlink_directory_and_file_never_touch_target(self):
        target = self.root / "untouched"
        target.mkdir()
        (self.root / "aparte").symlink_to(target, target_is_directory=True)
        technical_log.write_event("invoked")
        self.assertEqual(list(target.iterdir()), [])
        (self.root / "aparte").unlink()
        self.logs.mkdir(parents=True)
        secret = self.root / "secret"
        secret.write_text("private")
        (self.logs / "hotkey.jsonl").symlink_to(secret)
        technical_log.write_event("invoked")
        self.assertEqual(secret.read_text(), "private")

    def test_hard_link_and_fifo_are_rejected_without_blocking(self):
        self.logs.mkdir(parents=True)
        target = self.root / "target"
        target.write_text("keep")
        log = self.logs / "hotkey.jsonl"
        os.link(target, log)
        technical_log.write_event("invoked")
        self.assertEqual(target.read_text(), "keep")
        log.unlink()
        os.mkfifo(log)
        technical_log.write_event("invoked")

    def test_maximum_audio_diagnostic_fits_in_log(self):
        technical_log.write_event("audio_start_failed", audio_diagnostic="\u0001" * 9000)
        self.assertLessEqual((self.logs / "hotkey.jsonl").stat().st_size, technical_log.MAX_BYTES)

    def test_parallel_processes_produce_whole_json_entries(self):
        code = "from aparte.technical_log import write_event\nfor _ in range(100): write_event('invoked')"
        processes = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(4)]
        for process in processes:
            self.assertEqual(process.wait(timeout=10), 0)
        events = (self.logs / "hotkey.jsonl").read_text().splitlines()
        self.assertTrue(events)
        for line in events:
            self.assertEqual(json.loads(line)["event"], "invoked")


class HotkeyPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith(("APARTE_", "MURMUR_")):
                del self.env[key]
        self.env.update({"APARTE_CONFIG": str(self.root / "config.json"),
                         **{key: str(self.root / key) for key in (
                             "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME")}})

    def run_code(self, code):
        return subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True, timeout=10)

    def log_text(self):
        return "".join(p.read_text() for p in (self.root / "XDG_STATE_HOME/aparte/logs").glob("*.jsonl*"))

    def test_success_discards_python_native_and_child_output(self):
        result = self.run_code('''
from unittest.mock import patch
from aparte import cli
import os, subprocess, sys, ctypes

def fake(*args):
    print('SECRET_PYTHON')
    os.write(1, b'SECRET_NATIVE')
    os.write(2, b'SECRET_STDERR')
    ctypes.CDLL(None).printf(b'SECRET_BUFFERED_NATIVE')
    subprocess.run([sys.executable, '-c', "print('SECRET_CHILD')"])
    return 'SECRET_DICTATION'
with patch.object(cli, 'toggle_dictation', side_effect=fake):
    raise SystemExit(cli.main(['toggle', '--hotkey']))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertNotIn("SECRET", self.log_text())
        self.assertIn("completed", self.log_text())

    def test_exception_arguments_are_not_logged(self):
        result = self.run_code('''
from unittest.mock import patch
from aparte import cli
import subprocess
error = subprocess.CalledProcessError(1, ['xdotool', 'type', 'SECRET_DICTATION'])
with patch.object(cli, 'toggle_dictation', side_effect=error):
    raise SystemExit(cli.main(['toggle', '--hotkey']))
''')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertNotIn("SECRET", self.log_text())
        self.assertIn("CalledProcessError", self.log_text())

    def test_settings_failure_does_not_escape_privacy_scope(self):
        result = self.run_code('''
from unittest.mock import patch
from aparte import cli
with patch.object(cli.Settings, 'from_env', side_effect=ValueError('SECRET_CONFIGURATION')):
    raise SystemExit(cli.main(['toggle', '--hotkey']))
''')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertNotIn("SECRET", self.log_text())
        self.assertIn("ValueError", self.log_text())

    def test_explicit_stdout_keeps_cli_contract(self):
        result = self.run_code('''
from unittest.mock import patch
from aparte import cli
with patch.object(cli, 'toggle_dictation', return_value='DICTATED_TEXT'):
    raise SystemExit(cli.main(['toggle', '--target', 'stdout']))
''')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "DICTATED_TEXT\n")
        self.assertEqual(self.log_text(), "")

    def test_conflicting_stdout_flag_is_rejected(self):
        result = self.run_code("from aparte.cli import main; main(['toggle', '--hotkey', '--target', 'stdout'])")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be combined", result.stderr)

    def test_alsa_details_survive_but_only_at_start_failure(self):
        result = self.run_code('''
from unittest.mock import patch
from contextlib import nullcontext
from aparte import cli
from aparte.session import RecordingStartError
error = RecordingStartError('Micro absent', 'utc=2026-09-19 exit=1 device=USB ALSA: Input/output error')
with patch.object(cli, 'toggle_session_transition', side_effect=nullcontext), \\
     patch.object(cli, 'get_active_session', return_value=None), \\
     patch.object(cli, 'start_toggle_recording', side_effect=error), \\
     patch.object(cli, 'play_beep'), patch.object(cli, 'notify'):
    raise SystemExit(cli.main(['toggle', '--hotkey']))
''')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertIn("exit=1 device=USB ALSA: Input/output error", self.log_text())

    def test_log_failure_does_not_prevent_delivery(self):
        result = self.run_code('''
from unittest.mock import patch
from aparte import cli, technical_log
with patch.object(technical_log, '_directory', side_effect=OSError('disk full')), \\
     patch.object(cli, 'toggle_dictation', return_value='SECRET_DICTATION') as dictate:
    code = cli.main(['toggle', '--hotkey'])
    assert dictate.call_count == 1
    raise SystemExit(code)
''')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout + result.stderr, "")

    def test_shutdown_handlers_cannot_leak_text_after_main_returns(self):
        result = self.run_code('''
from unittest.mock import patch
from aparte import cli
import atexit, ctypes, os, sys

def backend_shutdown():
    print('SECRET_ATEXIT_PRINT')
    print('SECRET_ATEXIT_STDERR', file=sys.stderr)
    os.write(1, b'SECRET_ATEXIT_FD1')
    os.write(2, b'SECRET_ATEXIT_FD2')
    ctypes.CDLL(None).printf(b'SECRET_ATEXIT_BUFFERED_NATIVE')

atexit.register(backend_shutdown)
with patch.object(cli, 'toggle_dictation', return_value='SECRET_DICTATION'):
    raise SystemExit(cli.main(['toggle', '--hotkey']))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertNotIn("SECRET", self.log_text())
