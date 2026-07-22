import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import update


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def make_checkout(root: Path) -> Path:
    """A clone whose remote is called "Murmur", one commit behind its upstream."""
    source = root / "source"
    source.mkdir()
    git(source, "init", "--initial-branch=main")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test")
    (source / "README.md").write_text("un\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "premier commit")

    clone = root / "clone"
    subprocess.run(
        ["git", "clone", "--origin", "Murmur", str(source), str(clone)],
        check=True,
        capture_output=True,
    )

    (source / "README.md").write_text("deux\n", encoding="utf-8")
    git(source, "commit", "-am", "deuxième commit")
    return clone


class CheckUpdateTest(unittest.TestCase):
    def test_reads_the_real_tracking_branch_not_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                status = update.check_update(fetch=True)

            self.assertEqual(status["state"], "available")
            self.assertEqual(status["upstream"], "Murmur/main")
            self.assertEqual(status["behind"], 1)
            self.assertIn("deuxième commit", status["commits"][0])
            self.assertFalse(status["dirty"])

    def test_stays_offline_until_asked_to_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                status = update.check_update()

            self.assertEqual(status["state"], "current")
            self.assertEqual(status["behind"], 0)

    def test_local_changes_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            (clone / "README.md").write_text("modifié\n", encoding="utf-8")
            with mock.patch.object(update, "find_repo", return_value=clone):
                self.assertTrue(update.check_update()["dirty"])

    def test_branch_without_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            git(clone, "checkout", "-b", "essai")
            with mock.patch.object(update, "find_repo", return_value=clone):
                status = update.check_update()

            self.assertEqual(status["state"], "no_upstream")
            self.assertEqual(status["branch"], "essai")

    def test_outside_a_checkout(self):
        with mock.patch.object(update, "find_repo", return_value=None):
            self.assertEqual(update.check_update(fetch=True)["state"], "manual")


class ApplyUpdateTest(unittest.TestCase):
    def test_refuses_a_checkout_with_local_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            (clone / "README.md").write_text("modifié\n", encoding="utf-8")
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "_stream") as stream:
                    log = list(update.apply_update())

            stream.assert_not_called()
            self.assertIn("uncommitted", log[0])
            self.assertNotIn(update.DONE_MARKER, log)

    def test_refuses_a_branch_without_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            git(clone, "checkout", "-b", "essai")
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "_stream") as stream:
                    log = list(update.apply_update())

            stream.assert_not_called()
            self.assertIn("essai", log[0])

    def test_refuses_outside_a_checkout(self):
        with mock.patch.object(update, "find_repo", return_value=None):
            with mock.patch.object(update, "_stream") as stream:
                log = list(update.apply_update())

        stream.assert_not_called()
        self.assertIn("git checkout", log[0])

    def test_pulls_then_reinstalls_the_extras_already_present(self):
        commands = []

        def fake_stream(command, cwd):
            commands.append(command)
            yield "ok"
            return 0

        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "_stream", fake_stream):
                    with mock.patch.object(update, "_installed_extras", return_value=["whisper", "cuda"]):
                        log = list(update.apply_update())

        self.assertEqual(log[-1], update.DONE_MARKER)
        self.assertEqual(commands[0][:2], ["git", "-C"])
        self.assertIn("pull", commands[0])
        self.assertEqual(commands[1][-3:], ["install", "-e", ".[whisper,cuda]"])

    def test_a_failed_pull_installs_nothing(self):
        def failing_stream(command, cwd):
            yield "fatal: could not read from remote"
            return 1

        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "_stream", failing_stream):
                    log = list(update.apply_update())

        self.assertIn("Nothing was installed", log[-1])
        self.assertNotIn(update.DONE_MARKER, log)


if __name__ == "__main__":
    unittest.main()
