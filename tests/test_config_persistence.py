"""Concurrent writers and interrupted writes, with synthetic private settings."""

import errno
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from aparte import config


class ConfigPersistenceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="aparte-config-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "settings" / "config.json"
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("APARTE_", "MURMUR_"))
        }
        environment["APARTE_CONFIG"] = str(self.path)
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                    "XDG_RUNTIME_DIR", "XDG_CACHE_HOME"):
            environment[key] = str(self.root / key.lower())
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        patch = mock.patch.dict(os.environ, environment, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def child(self, source):
        prefix = "from pathlib import Path\nimport sys\nfrom aparte import config\n"
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", prefix + textwrap.dedent(source)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

        self.addCleanup(cleanup)
        return process

    def ready(self, process):
        readable, _, _ = select.select([process.stdout], [], [], 5)
        self.assertTrue(readable, "child did not reach the coordination point")
        self.assertEqual(process.stdout.readline().strip(), "ready")

    def release(self, process):
        process.stdin.write("continue\n")
        process.stdin.flush()

    def finished(self, process):
        output, error = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, error)
        return output

    def paused_update(self):
        process = self.child('''
            original = config._atomic_write
            def paused(path, data):
                print("ready", flush=True)
                sys.stdin.readline()
                original(path, data)
            config._atomic_write = paused
            config.update_config({"model": "base"})
        ''')
        self.ready(process)
        return process

    def test_two_processes_keep_both_independent_updates(self):
        config.write_default_config()
        first = self.paused_update()
        second = self.child('''
            print("ready", flush=True)
            config.update_config({"language": "fr"})
        ''')
        self.ready(second)
        with self.assertRaises(subprocess.TimeoutExpired):
            second.wait(timeout=0.15)
        self.release(first)
        self.finished(first)
        self.finished(second)
        actual = config.load_config()
        self.assertEqual(actual["model"], "base")
        self.assertEqual(actual["language"], "fr")

    def test_reader_sees_complete_previous_file_during_partial_write(self):
        config.update_config({"model": "small"})
        writer = self.child('''
            original = config.json.dump
            def paused(data, handle, **kwargs):
                handle.write('{"model":')
                handle.flush()
                print("ready", flush=True)
                sys.stdin.readline()
                handle.seek(0)
                handle.truncate()
                original(data, handle, **kwargs)
            config.json.dump = paused
            config.update_config({"model": "medium"})
        ''')
        self.ready(writer)
        self.assertEqual(config.load_config()["model"], "small")
        temporary = list(self.path.parent.glob(".config.json-*.tmp"))
        self.assertEqual(len(temporary), 1)
        self.assertEqual(stat.S_IMODE(temporary[0].stat().st_mode), 0o600)
        self.release(writer)
        self.finished(writer)
        self.assertEqual(config.load_config()["model"], "medium")

    def test_failed_partial_writes_preserve_old_config_and_remove_temporary(self):
        config.update_config({"model": "medium"})
        before = self.path.read_bytes()

        def disk_full(data, handle, **kwargs):
            handle.write('{"model":')
            handle.flush()
            raise OSError(errno.ENOSPC, "synthetic disk full")

        for action in (lambda: config.update_config({"model": "base"}),
                       lambda: config.write_default_config(force=True)):
            with self.subTest(action=action), mock.patch.object(config.json, "dump", disk_full):
                with self.assertRaises(OSError):
                    action()
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        # An exception must also release the writer lock.
        config.update_config({"beep": True})
        self.assertTrue(config.load_config()["beep"])

    def test_failed_fsync_preserves_old_config(self):
        config.write_default_config()
        before = self.path.read_bytes()
        with mock.patch.object(config.os, "fsync", side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                config.update_config({"model": "base"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_existing_json_is_not_silently_replaced(self):
        self.path.parent.mkdir()
        for invalid in ('{"model":', '[]', 'null', '"text"'):
            with self.subTest(invalid=invalid):
                self.path.write_text(invalid, encoding="utf-8")
                with self.assertRaises(ValueError):
                    config.update_config({"beep": True})
                self.assertEqual(self.path.read_text(encoding="utf-8"), invalid)
                with self.assertRaises(FileExistsError):
                    config.write_default_config()
        # Deliberate force reset remains available at this API boundary.
        config.write_default_config(force=True)
        self.assertEqual(config.load_config()["model"], "small")

    def test_files_are_private_without_changing_an_existing_parent(self):
        config.write_default_config()
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        for name in ("config.json", "config.json.lock"):
            self.assertEqual(stat.S_IMODE((self.path.parent / name).stat().st_mode), 0o600)
        self.path.parent.chmod(0o755)
        self.path.chmod(0o644)
        config.update_config({"beep": True})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o755)

    def test_lock_wait_is_bounded_and_does_not_change_config(self):
        config.write_default_config()
        before = self.path.read_bytes()
        writer = self.paused_update()
        with mock.patch.object(config, "_LOCK_TIMEOUT_SECONDS", 0.05):
            with self.assertRaisesRegex(TimeoutError, "Configuration occupée"):
                config.update_config({"beep": True})
        self.assertEqual(self.path.read_bytes(), before)
        self.release(writer)
        self.finished(writer)

    def test_non_force_init_does_not_overwrite_a_concurrent_creator(self):
        writer = self.paused_update()
        initializer = self.child('''
            print("ready", flush=True)
            try:
                config.write_default_config()
            except FileExistsError:
                pass
            else:
                raise AssertionError("non-force init overwrote existing config")
        ''')
        self.ready(initializer)
        with self.assertRaises(subprocess.TimeoutExpired):
            initializer.wait(timeout=0.15)
        self.release(writer)
        self.finished(writer)
        self.finished(initializer)
        self.assertEqual(config.load_config()["model"], "base")

    def legacy_paths(self):
        os.environ.pop("APARTE_CONFIG")
        legacy = config.get_legacy_config_path()
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"model": "medium", "custom": "kept"}', encoding="utf-8")
        return legacy, config.get_config_path()

    def test_first_update_migrates_legacy_and_preserves_unknown_existing_keys(self):
        legacy, current = self.legacy_paths()
        config.update_config({"beep": True, "bogus": 42})
        actual = config.load_config()
        self.assertEqual(actual["model"], "medium")
        self.assertEqual(actual["custom"], "kept")
        self.assertTrue(actual["beep"])
        self.assertNotIn("bogus", actual)
        self.assertFalse(legacy.exists())
        self.assertEqual(stat.S_IMODE(current.stat().st_mode), 0o600)

    def test_migration_does_not_overwrite_a_concurrent_creator(self):
        legacy, current = self.legacy_paths()
        writer = self.child('''
            original = config._atomic_write
            def paused(path, data):
                print("ready", flush=True)
                sys.stdin.readline()
                original(path, data)
            config._atomic_write = paused
            config.update_config({"model": "base"}, config.get_config_path())
        ''')
        self.ready(writer)
        migration = self.child('''
            print("ready", flush=True)
            config.migrate_legacy_config()
        ''')
        self.ready(migration)
        with self.assertRaises(subprocess.TimeoutExpired):
            migration.wait(timeout=0.15)
        self.release(writer)
        self.finished(writer)
        self.finished(migration)
        self.assertEqual(config.load_config()["model"], "base")
        self.assertTrue(legacy.exists())

    def test_invalid_or_failed_migration_keeps_legacy_original(self):
        legacy, current = self.legacy_paths()
        before = legacy.read_bytes()
        with mock.patch.object(config.os, "replace", side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                config.migrate_legacy_config()
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse(current.exists())
        legacy.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            config.migrate_legacy_config()
        self.assertEqual(legacy.read_text(encoding="utf-8"), "[]")
        self.assertFalse(current.exists())

    def test_migration_succeeds_even_if_old_copy_cannot_be_removed(self):
        legacy, current = self.legacy_paths()
        original_unlink = Path.unlink

        def refuse_legacy(path, *args, **kwargs):
            if path == legacy:
                raise PermissionError("synthetic read-only legacy directory")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", refuse_legacy):
            self.assertEqual(config.migrate_legacy_config(), current)
        self.assertTrue(legacy.exists())
        self.assertEqual(config.load_config()["model"], "medium")
        config.update_config({"model": "base"})
        self.assertEqual(config.load_config()["model"], "base")

    def test_symlink_config_uses_the_target_without_replacing_link(self):
        config.write_default_config()
        link = self.root / "linked-config.json"
        link.symlink_to(self.path)
        config.update_config({"model": "base"}, link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(config.load_config()["model"], "base")
        self.assertFalse((self.root / "linked-config.json.lock").exists())

    def test_lock_links_are_rejected_without_changing_their_target(self):
        config.write_default_config()
        lock = self.path.with_name("config.json.lock")
        lock.unlink()
        target = self.root / "unrelated"
        target.write_text("untouched", encoding="utf-8")
        target.chmod(0o644)
        for link_type in ("symbolic", "hard"):
            with self.subTest(link_type=link_type):
                if link_type == "symbolic":
                    lock.symlink_to(target)
                else:
                    os.link(target, lock)
                try:
                    with self.assertRaises(OSError):
                        config.update_config({"model": "base"})
                    self.assertEqual(target.read_text(encoding="utf-8"), "untouched")
                    self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
                finally:
                    lock.unlink()


if __name__ == "__main__":
    unittest.main()
