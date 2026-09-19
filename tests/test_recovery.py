import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import uuid
import unittest
from unittest import mock

from aparte import recovery


def _save_until_killed(source, connection):
    """Pause a real writer after partial audio + torn metadata, before unlock."""
    def partial_copy(_source, target):
        target.write(b"synthetic interrupted audio")
        target.flush()
        directory = Path(os.readlink(f"/proc/self/fd/{target.fileno()}" )).parent
        (directory / "metadata.json").write_text("{", encoding="utf-8")
        connection.send(str(directory))
        connection.recv()
    with mock.patch.object(recovery.shutil, "copyfileobj", side_effect=partial_copy):
        recovery.save_failure(Path(source))


def _hold_incomplete_directory(directory, connection):
    with recovery._locked(Path(directory), require_metadata=False):
        connection.send("locked")
        connection.recv()


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.environment = mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": self.tmp.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = Path(self.tmp.name) / "capture.webm"
        self.source.write_bytes(b"synthetic audio, never a real microphone")

    def test_private_capture_and_safe_listing(self):
        identifier = recovery.save_failure(self.source, raw_text="texte confidentiel")
        entries = recovery.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(set(entries[0]), {"id", "created_at", "expires_at", "has_text", "busy"})
        self.assertTrue(entries[0]["has_text"])
        self.assertNotIn("confidentiel", str(entries))
        self.assertNotIn(str(self.source), str(entries))
        with recovery.claim(identifier) as item:
            self.assertEqual(item.audio_path.suffix, ".webm")
            self.assertEqual(item.audio_path.read_bytes(), self.source.read_bytes())
            self.assertEqual(item.raw_text, "texte confidentiel")
            self.assertEqual(item.audio_path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(item.audio_path.parent.parent.stat().st_mode & 0o777, 0o700)
            for path in item.audio_path.parent.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.source.exists())

    def test_claim_excludes_another_retry_deletion_and_expiration(self):
        identifier = recovery.save_failure(self.source)
        with recovery.claim(identifier) as item:
            with self.assertRaises(recovery.RecoveryBusy):
                with recovery.claim(identifier):
                    self.fail("second retry entered")
            with self.assertRaises(recovery.RecoveryBusy):
                recovery.discard(identifier)
            self.assertTrue(recovery.entries()[0]["busy"])
            self.assertEqual(recovery.sweep(now=item.expires_at + 1), 0)
            self.assertTrue(item.audio_path.exists())
        self.assertEqual(recovery.sweep(now=item.expires_at + 1), 1)
        self.assertFalse(item.audio_path.exists())

    def test_failed_retry_keeps_same_entry_and_original_expiry(self):
        identifier = recovery.save_failure(self.source)
        original = recovery.entries()[0]
        with self.assertRaisesRegex(RuntimeError, "polish failed"):
            with recovery.claim(identifier) as item:
                recovery.update_raw(item, "brut récupérable")
                raise RuntimeError("polish failed")
        entry = recovery.entries()[0]
        self.assertEqual(entry["id"], identifier)
        self.assertEqual(entry["expires_at"], original["expires_at"])
        self.assertTrue(entry["has_text"])
        self.assertFalse(entry["busy"])

    def test_success_and_explicit_delete_remove_audio_and_text(self):
        first = recovery.save_failure(self.source, raw_text="secret")
        second = recovery.save_failure(self.source)
        with recovery.claim(first) as item:
            directory = item.audio_path.parent
            recovery.complete(item)
        self.assertFalse(directory.exists())
        recovery.discard(second)
        self.assertEqual(recovery.entries(), [])
        with self.assertRaises(recovery.RecoveryNotFound):
            with recovery.claim(first):
                self.fail("completed capture reused")

    def test_expired_capture_cannot_be_retried(self):
        with mock.patch.object(recovery.time, "time", return_value=100):
            identifier = recovery.save_failure(self.source)
        with mock.patch.object(recovery.time, "time", return_value=3700):
            with self.assertRaises(recovery.RecoveryNotFound):
                with recovery.claim(identifier):
                    self.fail("expired capture reused")
        self.assertEqual(recovery.entries(), [])

    def test_unsafe_identifier_and_symlink_are_rejected(self):
        with self.assertRaises(recovery.RecoveryNotFound):
            with recovery.claim("../../capture"):
                self.fail("path traversal accepted")
        identifier = recovery.save_failure(self.source)
        with recovery.claim(identifier) as item:
            audio = item.audio_path
        audio.unlink()
        audio.symlink_to(self.source)
        with self.assertRaises(OSError):
            with recovery.claim(identifier):
                self.fail("audio symlink accepted")
        recovery.sweep(now=float("inf"))
        self.assertTrue(self.source.exists())

    def test_symlinked_store_is_rejected_without_changing_target(self):
        root = recovery._root()
        root.rmdir()
        other = Path(self.tmp.name) / "other"
        other.mkdir(mode=0o755)
        root.symlink_to(other, target_is_directory=True)
        with self.assertRaises(recovery.RecoveryError):
            recovery.save_failure(self.source)
        self.assertEqual(other.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(other.iterdir()), [])

    def test_partial_copy_failure_does_not_leave_a_second_capture(self):
        with mock.patch.object(recovery.shutil, "copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                recovery.save_failure(self.source)
        self.assertTrue(self.source.exists())
        self.assertEqual(recovery.entries(), [])


    def test_corrupt_metadata_is_hidden_and_expires_from_stable_creation_time(self):
        now = time.time()
        invalid = [
            "{", "[]", "null", '"text"',
            json.dumps({"suffix": ".wav", "created_at": now, "expires_at": float("nan")}),
            json.dumps({"suffix": ".wav", "created_at": now, "expires_at": float("inf")}),
            json.dumps({"suffix": ".wav", "created_at": True, "expires_at": now}),
            json.dumps({"suffix": ".wav", "created_at": now, "expires_at": now - 1}),
            json.dumps({"suffix": ".wav", "created_at": now, "expires_at": now + 3601}),
        ]
        for contents in invalid:
            with self.subTest(contents=contents):
                identifier = recovery.save_failure(self.source)
                directory = recovery._root() / identifier
                marker = directory / "lock"
                born = marker.stat().st_mtime
                (directory / "metadata.json").write_text(contents, encoding="utf-8")
                self.assertEqual(recovery.entries(), [])
                with self.assertRaises(recovery.RecoveryError):
                    with recovery.claim(identifier):
                        self.fail("invalid metadata accepted")
                self.assertEqual(recovery.sweep(now=born + 3599), 0)
                self.assertEqual(recovery.sweep(now=born + 3600), 1)
                self.assertFalse(directory.exists())

    def test_corrupt_retry_does_not_extend_fallback_expiry(self):
        identifier = recovery.save_failure(self.source)
        directory = recovery._root() / identifier
        marker = directory / "lock"
        born = marker.stat().st_mtime
        with recovery.claim(identifier) as item:
            recovery.update_raw(item, "transcription retained")
        (directory / "metadata.json").write_text("{}", encoding="utf-8")
        os.utime(directory, (born + 3500, born + 3500))
        self.assertEqual(marker.stat().st_mtime, born)
        self.assertEqual(recovery.sweep(now=born + 3600), 1)

    def test_incomplete_directory_without_metadata_or_marker_expires(self):
        directory = recovery._root() / uuid.uuid4().hex
        directory.mkdir(mode=0o700)
        (directory / "audio.wav").write_bytes(b"interrupted capture")
        born = directory.stat().st_mtime
        self.assertEqual(recovery.sweep(now=born + 3599), 0)
        self.assertFalse((directory / "lock").exists())
        self.assertEqual(recovery.sweep(now=born + 3600), 1)
        self.assertFalse(directory.exists())

    def _child(self, target, *args):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe()
        process = context.Process(target=target, args=(*args, sender))
        process.start()
        sender.close()
        def cleanup():
            if process.is_alive():
                process.kill()
            process.join(timeout=3)
            receiver.close()
        self.addCleanup(cleanup)
        self.assertTrue(receiver.poll(3), "child failed to acquire capture")
        return process, receiver.recv()

    def test_killed_partial_save_is_protected_while_active_then_expires(self):
        process, name = self._child(_save_until_killed, str(self.source))
        directory = Path(name)
        born = (directory / "lock").stat().st_mtime
        self.assertEqual(recovery.entries(), [])
        self.assertEqual(recovery.sweep(now=born + 3601), 0)
        self.assertTrue(directory.exists())
        process.kill()
        process.join(timeout=3)
        self.assertFalse(process.is_alive())
        self.assertEqual(recovery.sweep(now=born + 3601), 1)
        self.assertFalse(directory.exists())
        self.assertTrue(self.source.exists())

    def test_incomplete_directory_claim_blocks_cleanup_without_recreating_lock(self):
        directory = recovery._root() / uuid.uuid4().hex
        directory.mkdir(mode=0o700)
        (directory / "audio.wav").write_bytes(b"synthetic incomplete capture")
        born = directory.stat().st_mtime
        process, _ = self._child(_hold_incomplete_directory, str(directory))
        self.assertEqual(recovery.sweep(now=born + 3601), 0)
        self.assertFalse((directory / "lock").exists())
        process.kill()
        process.join(timeout=3)
        self.assertEqual(recovery.sweep(now=born + 3601), 1)
        self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
