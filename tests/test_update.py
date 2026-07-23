import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import update


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


INSTALLED = "1.0.0"


def make_checkout(root: Path, release: str | None = "v1.0.1") -> Path:
    """A clone sitting on v1.0.0, whose remote is called "Murmur".

    The source then gains an unreleased commit and, unless `release` is None, a
    newer tag — so a test can tell "somebody pushed a commit" apart from
    "somebody cut a release".
    """
    source = root / "source"
    source.mkdir()
    git(source, "init", "--initial-branch=main")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test")
    (source / "README.md").write_text("un\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "premier commit")
    git(source, "tag", "-a", "v1.0.0", "-m", "1.0.0")

    clone = root / "clone"
    subprocess.run(
        ["git", "clone", "--origin", "Murmur", str(source), str(clone)],
        check=True,
        capture_output=True,
    )

    (source / "README.md").write_text("deux\n", encoding="utf-8")
    git(source, "commit", "-am", "docs: une virgule en trop")
    if release:
        (source / "README.md").write_text("trois\n", encoding="utf-8")
        git(source, "commit", "-am", "fix: quelque chose d'important")
        git(source, "tag", "-a", release, "-m", release)
    return clone


class VersionTagTest(unittest.TestCase):
    def test_versions_compare_as_numbers_not_as_text(self):
        self.assertGreater(update._version_key("v1.10.0"), update._version_key("v1.9.0"))

    def test_anything_that_is_not_a_plain_release_is_not_a_candidate(self):
        for tag in ("v2.0.0-rc1", "nightly", "v1.0", "1.0.0"):
            self.assertIsNone(update._version_key(tag), tag)


class CheckUpdateTest(unittest.TestCase):
    def test_reads_the_real_tracking_branch_not_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    status = update.check_update(fetch=True)

            self.assertEqual(status["state"], "available")
            self.assertEqual(status["upstream"], "Murmur/main")
            self.assertEqual(status["release"], "v1.0.1")
            self.assertEqual(status["version"], INSTALLED)
            self.assertFalse(status["dirty"])

    def test_a_commit_without_a_release_is_not_an_update(self):
        """Le cœur du choix : un `docs:` poussé sur main n'est pas une version.

        Avant, il déclenchait une notification de mise à jour et un
        réinstallation complète pour une virgule.
        """
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory), release=None)
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    status = update.check_update(fetch=True)

            self.assertEqual(status["state"], "current")
            self.assertEqual(status["release"], "v1.0.0")

    def test_the_release_contents_are_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    status = update.check_update(fetch=True)

            self.assertTrue(any("important" in line for line in status["commits"]))

    def test_stays_offline_until_asked_to_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    status = update.check_update()

            self.assertEqual(status["state"], "current")

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
            git(clone, "fetch", "--tags", "Murmur")
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
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

    def test_refuses_when_already_on_the_newest_release(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory), release=None)
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    with mock.patch.object(update, "_stream") as stream:
                        log = list(update.apply_update())

            stream.assert_not_called()
            self.assertIn("newest release", log[0])

    def test_moves_to_the_tag_then_reinstalls_the_extras_already_present(self):
        commands = []

        def fake_stream(command, cwd):
            commands.append(command)
            yield "ok"
            return 0

        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            git(clone, "fetch", "--tags", "Murmur")
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    with mock.patch.object(update, "_stream", fake_stream):
                        with mock.patch.object(
                            update, "_installed_extras", return_value=["whisper", "cuda"]
                        ):
                            log = list(update.apply_update())

        self.assertEqual(log[-1], update.DONE_MARKER)
        self.assertEqual(commands[0][:2], ["git", "-C"])
        # Jusqu'au tag, pas jusqu'à la pointe de la branche : le commit non
        # publié qui suit v1.0.1 ne doit pas arriver chez un utilisateur.
        self.assertEqual(commands[0][-3:], ["merge", "--ff-only", "v1.0.1"])
        self.assertNotIn("pull", commands[0])
        self.assertIn("-e", commands[1])
        self.assertEqual(commands[1][-3:], ["install", "-e", ".[whisper,cuda]"])

    def test_a_failed_move_installs_nothing(self):
        def failing_stream(command, cwd):
            yield "fatal: could not read from remote"
            return 1

        with tempfile.TemporaryDirectory() as directory:
            clone = make_checkout(Path(directory))
            git(clone, "fetch", "--tags", "Murmur")
            with mock.patch.object(update, "find_repo", return_value=clone):
                with mock.patch.object(update, "__version__", INSTALLED):
                    with mock.patch.object(update, "_stream", failing_stream):
                        log = list(update.apply_update())

        self.assertIn("Nothing was installed", log[-1])
        self.assertNotIn(update.DONE_MARKER, log)


class RestartTest(unittest.TestCase):
    def _relaunch_command(self, argv):
        with mock.patch.object(update.os, "execv") as execv:
            with mock.patch.object(update.sys, "argv", argv):
                update.restart()
        return execv.call_args[0][1][1:]

    def test_a_console_script_is_rerun_as_is(self):
        self.assertEqual(
            self._relaunch_command(["/home/x/.local/bin/aparte", "desktop"]),
            ["/home/x/.local/bin/aparte", "desktop"],
        )

    def test_a_module_run_goes_back_through_dash_m(self):
        """Re-running src/aparte/__main__.py directly breaks the relative imports."""
        self.assertEqual(
            self._relaunch_command(["/src/aparte/__main__.py", "desktop", "--no-browser"]),
            ["-m", "aparte", "desktop", "--no-browser"],
        )


if __name__ == "__main__":
    unittest.main()
