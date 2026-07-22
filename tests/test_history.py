import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import history


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patch = mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": self.directory.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_records_newest_first(self):
        history.record("première")
        history.record("deuxième")

        self.assertEqual([item["text"] for item in history.entries()], ["deuxième", "première"])
        self.assertEqual(history.last(), "deuxième")

    def test_keeps_only_the_last_five(self):
        for index in range(8):
            history.record(f"dictée {index}")

        texts = [item["text"] for item in history.entries()]
        self.assertEqual(len(texts), history.LIMIT)
        self.assertEqual(texts[0], "dictée 7")
        self.assertNotIn("dictée 2", texts)

    def test_dictating_the_same_thing_twice_moves_it_up(self):
        history.record("bonjour")
        history.record("autre chose")
        history.record("bonjour")

        self.assertEqual([item["text"] for item in history.entries()], ["bonjour", "autre chose"])

    def test_blank_dictations_are_not_recorded(self):
        history.record("   \n ")
        self.assertEqual(history.entries(), [])
        self.assertIsNone(history.last())

    def test_lives_in_the_runtime_directory_by_default(self):
        """Memory by default: a dictation can carry a password."""
        history.record("secret")
        self.assertEqual(history.get_history_path().parent, Path(self.directory.name))

    def test_persisting_writes_a_private_file_under_the_state_directory(self):
        with tempfile.TemporaryDirectory() as state:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": state}):
                history.record("gardé", persist=True)
                path = history.get_history_path(persist=True)

                self.assertEqual(path.parent, Path(state) / "aparte")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(history.last(persist=True), "gardé")
        # The two stores stay separate: nothing leaked into memory-backed storage.
        self.assertIsNone(history.last())

    def test_a_corrupt_file_reads_as_empty_instead_of_raising(self):
        history.get_history_path().write_text("{ pas du json", encoding="utf-8")
        self.assertEqual(history.entries(), [])

    def test_recording_never_raises_when_the_store_is_unwritable(self):
        """A dictation must not fail because its history could not be written."""
        with mock.patch.object(history, "_write", side_effect=OSError("disque plein")):
            history.record("ne doit pas exploser")

    def test_clear_empties_the_history(self):
        history.record("à oublier")
        history.clear()
        self.assertEqual(history.entries(), [])

    def test_entries_are_timestamped(self):
        history.record("quand")
        stored = json.loads(history.get_history_path().read_text(encoding="utf-8"))
        self.assertIsInstance(stored[0]["at"], float)


if __name__ == "__main__":
    unittest.main()
