"""The macOS temporary store is disk-backed and expires on the next access."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from aparte import history


class MacHistoryRetentionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aparte-history-retention-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root / "runtime"),
            **{key: str(self.root / key.lower()) for key in (
                "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME",
                "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
            )},
        }
        for patch in (mock.patch.dict(os.environ, environment),
                      mock.patch.object(history, "is_macos", return_value=True),
                      mock.patch.object(history.time, "time", return_value=1_000_000.0)):
            patch.start()
            self.addCleanup(patch.stop)
        self.now = 1_000_000.0

    def write(self, items, persist=False):
        path = history.get_history_path(persist)
        path.write_text(json.dumps(items), encoding="utf-8")
        return path

    def test_reads_remove_expired_entries_without_removing_recent_ones(self):
        recent = {"text": "récente", "at": self.now - 1}
        path = self.write([
            recent,
            {"text": "expirée", "at": self.now - history.TEMPORARY_MAX_AGE_SECONDS},
        ])
        self.assertEqual(history.entries(), [recent])
        self.assertEqual(json.loads(path.read_text()), [recent])

    def test_completely_expired_history_file_is_removed(self):
        path = self.write([{"text": "ancienne", "at": 1}])
        self.assertEqual(history.entries(), [])
        self.assertFalse(path.exists())
        self.assertTrue(path.with_suffix(".lock").exists())

    def test_new_dictation_prunes_old_entries(self):
        self.write([{"text": "ancienne", "at": 1}])
        history.record("nouvelle")
        self.assertEqual(history.entries(), [{"text": "nouvelle", "at": self.now}])

    def test_persistent_history_does_not_expire(self):
        items = [{"text": "conservée", "at": 1}]
        path = self.write(items, persist=True)
        self.assertEqual(history.entries(persist=True), items)
        self.assertTrue(path.exists())
        history.record("nouvelle", persist=True)
        self.assertEqual(len(history.entries(persist=True)), 2)

    def test_linux_runtime_history_keeps_session_policy(self):
        items = [{"text": "session", "at": 1}]
        self.write(items)
        with mock.patch.object(history, "is_macos", return_value=False):
            self.assertEqual(history.entries(), items)
            history.record("nouvelle")
            self.assertEqual(len(history.entries()), 2)

    def test_missing_invalid_and_future_timestamps_do_not_live_forever(self):
        self.write([{"text": "sans date"}] + [
            {"text": "date invalide", "at": stamp}
            for stamp in (None, "hier", True, float("nan"), float("inf"),
                          10 ** 1000, self.now + 60)
        ])
        self.assertEqual(history.entries(), [])
        self.assertFalse(history.get_history_path().exists())

    def test_expiry_rereads_under_lock_and_preserves_a_concurrent_writer(self):
        self.write([{"text": "ancienne", "at": 1}])
        lock = history._locked

        @contextmanager
        def another_writer_first(path):
            # Interleave a genuine publication after the reader's snapshot but
            # before it acquires the writer lock. Recursive record uses the real
            # lock; stale expiry data must not be written back afterwards.
            with mock.patch.object(history, "_locked", lock):
                history.record("publiée pendant la purge")
            with lock(path):
                yield

        with mock.patch.object(history, "_locked", another_writer_first):
            actual = history.entries()
        self.assertEqual(actual, [{"text": "publiée pendant la purge", "at": self.now}])
        self.assertEqual(history.entries(), actual)

    def test_failed_purge_never_returns_expired_text_or_raises(self):
        self.write([{"text": "ancienne", "at": 1}])
        with mock.patch.object(history, "_locked", side_effect=TimeoutError("busy")):
            self.assertEqual(history.entries(), [])
        self.assertEqual(history.entries(), [])
        self.assertFalse(history.get_history_path().exists())


if __name__ == "__main__":
    unittest.main()
