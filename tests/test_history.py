import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from aparte import history


def _record_together(barrier, text):
    original_write = history._write

    def slow_write(items, path):
        time.sleep(0.025)
        original_write(items, path)

    with mock.patch.object(history, "_write", side_effect=slow_write):
        barrier.wait(timeout=5)
        history.record(text)


def _paused_operation(operation, entered, release):
    if operation == "record":
        original = history._write

        def paused(items, path):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release writer")
            original(items, path)

        with mock.patch.object(history, "_write", side_effect=paused):
            history.record("nouvelle")
    else:
        original = Path.unlink

        def paused(path, *args, **kwargs):
            if path.name == "history.json":
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Test did not release clear")
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", paused):
            history.clear()


def _operation(operation, started, finished):
    started.set()
    if operation == "record":
        history.record("après effacement")
    else:
        history.clear()
    finished.set()


def _hold_lock(entered, release):
    with history._locked(history.get_history_path()):
        entered.set()
        release.wait(10)


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        patch = mock.patch.dict(os.environ, {
            "APARTE_RUNTIME_DIR": str(root),
            "APARTE_CONFIG": str(root / "config.json"),
            **{name: str(root / name) for name in (
                "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                "XDG_STATE_HOME", "XDG_CACHE_HOME",
            )},
        })
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

    def start_process(self, target, *args):
        process = multiprocessing.get_context("spawn").Process(target=target, args=args)
        process.start()

        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)

        self.addCleanup(cleanup)
        return process

    def finish_process(self, process):
        process.join(timeout=5)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)

    def test_concurrent_processes_keep_each_of_the_last_five_dictations(self):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(history.LIMIT)
        expected = {f"dictée {index}" for index in range(history.LIMIT)}
        processes = [self.start_process(_record_together, barrier, text) for text in expected]
        for process in processes:
            self.finish_process(process)
        self.assertEqual({item["text"] for item in history.entries()}, expected)

    def assert_operations_are_serialized(self, first, second, expected):
        history.record("ancienne")
        context = multiprocessing.get_context("spawn")
        entered, release, started, finished = (context.Event() for _ in range(4))
        self.addCleanup(release.set)
        first_process = self.start_process(_paused_operation, first, entered, release)
        self.assertTrue(entered.wait(5))
        second_process = self.start_process(_operation, second, started, finished)
        self.assertTrue(started.wait(5))
        self.assertFalse(finished.wait(0.05))
        release.set()
        self.finish_process(first_process)
        self.finish_process(second_process)
        self.assertEqual([item["text"] for item in history.entries()], expected)

    def test_clear_waits_for_writer_and_does_not_resurrect_old_entries(self):
        self.assert_operations_are_serialized("record", "clear", [])

    def test_writer_after_clear_keeps_only_the_new_dictation(self):
        self.assert_operations_are_serialized("clear", "record", ["après effacement"])

    def test_busy_history_has_bounded_wait_and_keeps_previous_data(self):
        history.record("gardée")
        context = multiprocessing.get_context("spawn")
        entered, release = context.Event(), context.Event()
        self.addCleanup(release.set)
        process = self.start_process(_hold_lock, entered, release)
        self.assertTrue(entered.wait(5))
        start = time.monotonic()
        history.record("non enregistrée")
        history.clear()
        elapsed = time.monotonic() - start
        release.set()
        self.finish_process(process)
        self.assertLess(elapsed, 5)
        self.assertEqual(history.last(), "gardée")

    def test_disk_failure_preserves_old_file_and_removes_private_temporary(self):
        history.record("gardée")
        path = history.get_history_path()
        before = path.read_bytes()
        with mock.patch.object(history.os, "fsync", side_effect=OSError("disque plein")):
            history.record("nouvelle")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".history.json-*.tmp")), [])

    def test_replacement_failure_preserves_old_file(self):
        history.record("gardée")
        with mock.patch.object(Path, "replace", side_effect=OSError("remplacement refusé")):
            history.record("nouvelle")
        self.assertEqual(history.last(), "gardée")
        self.assertEqual(list(Path(self.directory.name).glob(".history.json-*.tmp")), [])

    def test_reader_keeps_its_snapshot_when_a_writer_replaces_the_file(self):
        history.record("avant")
        path = history.get_history_path()
        original_inode = path.stat().st_ino
        original_fstat = history.os.fstat

        def replace_before_stat(fd):
            info = original_fstat(fd)
            if info.st_ino == original_inode:
                history._write([{"text": "après", "at": time.time()}], path)
            return original_fstat(fd)

        with mock.patch.object(history.os, "fstat", side_effect=replace_before_stat):
            self.assertEqual(history.last(), "avant")
        self.assertEqual(history.last(), "après")

    def test_temporary_is_unique_and_private_before_any_text_is_written(self):
        original = history.json.dump
        seen = []

        def inspect(items, stream, **kwargs):
            temporary = list(Path(self.directory.name).glob(".history.json-*.tmp"))
            self.assertEqual(len(temporary), 1)
            self.assertEqual(temporary[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(temporary[0].stat().st_size, 0)
            seen.append(temporary[0])
            original(items, stream, **kwargs)

        with mock.patch.object(history.json, "dump", side_effect=inspect):
            history.record("une")
            history.record("deux")
        self.assertEqual(len(set(seen)), 2)

    def test_persistent_directory_is_private_without_changing_xdg_parent(self):
        parent = Path(os.environ["XDG_STATE_HOME"])
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        (parent / "aparte").mkdir(mode=0o755)
        history.record("privée", persist=True)
        self.assertEqual(parent.stat().st_mode & 0o777, 0o755)
        self.assertEqual((parent / "aparte").stat().st_mode & 0o777, 0o700)

    def test_persistent_directory_symlink_does_not_touch_target(self):
        parent = Path(os.environ["XDG_STATE_HOME"])
        parent.mkdir()
        target = Path(self.directory.name) / "ailleurs"
        target.mkdir(mode=0o755)
        (parent / "aparte").symlink_to(target, target_is_directory=True)
        history.record("ne pas écrire", persist=True)
        history.clear(persist=True)
        self.assertEqual(history.entries(persist=True), [])
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_history_and_lock_symlinks_never_read_or_modify_the_target(self):
        root = Path(self.directory.name)
        target = root / "ailleurs.json"
        target.write_text('[{"text": "privé"}]', encoding="utf-8")
        for filename in ("history.json", "history.lock"):
            with self.subTest(filename=filename):
                link = root / filename
                link.unlink(missing_ok=True)
                link.symlink_to(target)
                history.record("autre texte")
                if filename == "history.json":
                    self.assertEqual(history.entries(), [])
                self.assertTrue(link.is_symlink())
                self.assertEqual(target.read_text(encoding="utf-8"), '[{"text": "privé"}]')
                link.unlink()

    def test_clear_preserves_the_lock_inode(self):
        history.record("une")
        lock = Path(self.directory.name) / "history.lock"
        inode = lock.stat().st_ino
        history.clear()
        history.record("deux")
        self.assertEqual(lock.stat().st_ino, inode)


if __name__ == "__main__":
    unittest.main()
