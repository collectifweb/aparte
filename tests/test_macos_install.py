"""M7c — installer le bundle, et refuser de le casser par mégarde.

Tout est simulé : `clang` et `codesign` n'existent pas sur la machine de
développement, et ce qu'on vérifie ici est la **décision** — installer, ne rien
faire, ou s'arrêter — pas ce que macOS en fait. Cette partie-là est mesurée par
M7-0 sur un vrai Mac.
"""

import multiprocessing
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import macos_desktop, macos_install


def _hold_installation_lock(destination, ready, release):
    with macos_install._installation_lock(destination):
        ready.set()
        release.wait(10)


class CdhashTest(unittest.TestCase):
    def test_the_fingerprint_is_read_off_stderr(self):
        # `codesign -dvvv` écrit tout sur stderr : le lire sur stdout seulement
        # rendrait « empreinte illisible » sur un bundle parfaitement signé.
        done = mock.Mock(returncode=0, stdout="", stderr="Identifier=ca.collectifweb.aparte\nCDHash=ABC123def\n")
        with mock.patch.object(macos_install.subprocess, "run", return_value=done):
            self.assertEqual(macos_install.read_cdhash(Path("/x.app")), "abc123def")

    def test_an_unreadable_bundle_answers_none_rather_than_guessing(self):
        with mock.patch.object(macos_install.subprocess, "run", side_effect=OSError):
            self.assertIsNone(macos_install.read_cdhash(Path("/x.app")))

    def test_failed_description_does_not_accept_a_printed_fingerprint(self):
        done = mock.Mock(returncode=1, stdout="", stderr="CDHash=abc123\nerror")
        with mock.patch.object(macos_install.subprocess, "run", return_value=done):
            self.assertIsNone(macos_install.read_cdhash(Path("/x.app")))

    def test_the_reference_lives_outside_the_bundle(self):
        # La ranger dedans modifierait précisément ce qu'elle prétend surveiller.
        reference = macos_install.cdhash_reference_path()
        self.assertNotIn(macos_desktop.BUNDLE_NAME, str(reference))
        self.assertEqual(reference.name, macos_install.CDHASH_FILE)


class InstallTest(unittest.TestCase):
    """Les trois issues, et la seule qui doit s'arrêter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.destination = self.home / "Applications" / macos_desktop.BUNDLE_NAME
        patches = [
            mock.patch.object(macos_desktop, "bundle_path", return_value=self.destination),
            mock.patch.object(macos_install, "_run"),
            mock.patch.object(
                macos_install, "cdhash_reference_path", return_value=self.home / "reference"
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _install(self, fresh, installed=None, force=False):
        hashes = [fresh, installed, fresh] if self.destination.exists() else [fresh, fresh]
        with mock.patch.object(macos_install, "read_cdhash", side_effect=hashes):
            return macos_install.install_app("/opt/homebrew/opt/aparte/libexec/bin/python3",
                                             force=force)

    def test_a_first_install_puts_the_bundle_in_place(self):
        result = self._install("aaa")
        self.assertEqual(result["outcome"], "installed")
        self.assertTrue(self.destination.exists())
        self.assertEqual((self.home / "reference").read_text().strip(), "aaa")

    def test_the_same_fingerprint_changes_nothing(self):
        self._install("aaa")
        before = (self.destination / "Contents" / "Info.plist").stat().st_mtime_ns
        result = self._install("aaa", installed="aaa")
        self.assertEqual(result["outcome"], "unchanged")
        self.assertEqual(
            (self.destination / "Contents" / "Info.plist").stat().st_mtime_ns, before
        )

    def test_a_different_fingerprint_stops_and_says_what_it_would_cost(self):
        # Le cas qui compte : remplacer ferait oublier les autorisations à macOS,
        # en laissant les cases cochées. Ça se dit avant, pas après.
        self._install("aaa")
        with self.assertRaises(macos_install.InstallError) as raised:
            self._install("bbb", installed="aaa")
        message = str(raised.exception)
        self.assertIn("--force", message)
        self.assertIn("forget", message)

    def test_force_replaces_it_and_records_the_new_fingerprint(self):
        self._install("aaa")
        result = self._install("bbb", installed="aaa", force=True)
        self.assertEqual(result["outcome"], "replaced")
        self.assertEqual((self.home / "reference").read_text().strip(), "bbb")

    def test_an_unsignable_bundle_is_never_presented_as_installed(self):
        with self.assertRaises(macos_install.InstallError):
            self._install(None)
        self.assertFalse(self.destination.exists())

    def test_the_c_source_never_ships_inside_the_bundle(self):
        # Il serait signé avec le reste : l'empreinte dépendrait de lui.
        self._install("aaa")
        self.assertEqual(list(self.destination.rglob("*.c")), [])

    def test_build_and_both_signature_checks_run_on_the_destination_volume(self):
        with mock.patch.object(macos_install, "_run") as run:
            self._install("aaa")
        verified = [Path(call.args[0][-1]) for call in run.call_args_list
                    if "--verify" in call.args[0]]
        self.assertEqual(len(verified), 2)
        self.assertEqual(verified[0].parent.parent, self.destination.parent)
        self.assertEqual(verified[1], self.destination)
        self.assertEqual(list(self.destination.parent.glob(".aparte-install-*/")), [])

    def test_publication_failure_restores_previous_bundle_and_reference(self):
        self._install("aaa")
        marker = self.destination / "old-marker"
        marker.write_text("previous bundle")
        original = Path.rename

        def fail_publication(path, target):
            if path.name == macos_desktop.BUNDLE_NAME and path != self.destination:
                raise OSError("synthetic publication failure")
            return original(path, target)

        with mock.patch.object(Path, "rename", fail_publication):
            with self.assertRaises(macos_install.InstallError):
                self._install("bbb", installed="aaa", force=True)
        self.assertEqual(marker.read_text(), "previous bundle")
        self.assertEqual((self.home / "reference").read_text().strip(), "aaa")

    def test_post_publication_verification_failure_rolls_back(self):
        self._install("aaa")
        marker = self.destination / "old-marker"
        marker.write_text("previous bundle")

        def verify(command):
            if ("--verify" in command and Path(command[-1]) == self.destination
                    and not marker.exists()):
                raise macos_install.InstallError("synthetic signature failure")

        with mock.patch.object(macos_install, "_run", side_effect=verify):
            with self.assertRaises(macos_install.InstallError):
                self._install("bbb", installed="aaa", force=True)
        self.assertEqual(marker.read_text(), "previous bundle")
        self.assertEqual((self.home / "reference").read_text().strip(), "aaa")

    def test_failed_first_install_leaves_no_invalid_application(self):
        def verify(command):
            if "--verify" in command and Path(command[-1]) == self.destination:
                raise macos_install.InstallError("synthetic signature failure")

        with mock.patch.object(macos_install, "_run", side_effect=verify):
            with self.assertRaises(macos_install.InstallError):
                self._install("aaa")
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.home / "reference").exists())

    def test_failed_restore_keeps_the_backup_and_reports_its_location(self):
        self._install("aaa")
        (self.destination / "old-marker").write_text("previous bundle")
        original = Path.rename

        def fail(path, target):
            if path.name == "previous.app" or (path.name == macos_desktop.BUNDLE_NAME
                                               and path != self.destination):
                raise OSError("synthetic publication/restore failure")
            return original(path, target)

        with mock.patch.object(Path, "rename", fail):
            with self.assertRaises(macos_install.InstallError) as raised:
                self._install("bbb", installed="aaa", force=True)
        backups = list(self.destination.parent.glob(".aparte-install-*/previous.app"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "old-marker").read_text(), "previous bundle")
        self.assertIn(str(backups[0]), str(raised.exception))
        self.assertEqual((self.home / "reference").read_text().strip(), "aaa")

    def test_matching_cdhash_is_not_enough_when_existing_resources_are_invalid(self):
        self._install("aaa")

        def verify(command):
            if "--verify" in command and Path(command[-1]) == self.destination:
                raise macos_install.InstallError("resources modified")

        with mock.patch.object(macos_install, "_run", side_effect=verify):
            with self.assertRaisesRegex(macos_install.InstallError, "--force"):
                self._install("aaa", installed="aaa")

    def test_install_and_remove_cannot_race_another_process(self):
        self._install("aaa")
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        process = context.Process(target=_hold_installation_lock,
                                  args=(self.destination, ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(5))
            with mock.patch.object(macos_install, "_LOCK_TIMEOUT_SECONDS", 0.05):
                for action in (lambda: self._install("bbb", installed="aaa", force=True),
                               macos_install.uninstall_app):
                    with self.assertRaisesRegex(macos_install.InstallError, "in progress"):
                        action()
            self.assertTrue(self.destination.exists())
            self.assertEqual((self.home / "reference").read_text().strip(), "aaa")
        finally:
            release.set()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
        self.assertEqual(process.exitcode, 0)

    def test_a_bundle_symlink_never_modifies_its_target(self):
        other = self.home / "elsewhere.app"
        other.mkdir()
        self.destination.parent.mkdir()
        self.destination.symlink_to(other, target_is_directory=True)
        with self.assertRaises(macos_install.InstallError):
            self._install("aaa", force=True)
        with self.assertRaises(macos_install.InstallError):
            macos_install.uninstall_app()
        self.assertTrue(other.exists())


class UninstallTest(unittest.TestCase):
    """`brew uninstall` laisse le bundle en place — il vit hors du préfixe, exprès."""

    def test_it_removes_the_bundle_and_forgets_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            destination = home / "Applications" / macos_desktop.BUNDLE_NAME
            destination.mkdir(parents=True)
            reference = home / "reference"
            reference.write_text("aaa")
            with mock.patch.object(macos_desktop, "bundle_path", return_value=destination):
                with mock.patch.object(
                    macos_install, "cdhash_reference_path", return_value=reference
                ):
                    self.assertTrue(macos_install.uninstall_app())
                    self.assertFalse(destination.exists())
                    self.assertFalse(reference.exists())
                    self.assertFalse(macos_install.uninstall_app())


class OpenTest(unittest.TestCase):
    def test_it_goes_through_launch_services_not_the_launcher(self):
        # Lancer l'exécutable à la main ferait de ce processus-ci le responsable,
        # et tout l'intérêt du bundle est que ce soit LaunchServices.
        with mock.patch.object(macos_install, "_run") as run:
            macos_install.open_app()
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/open")


class PendingVerdictTest(unittest.TestCase):
    """Les deux choix que M7-0 doit confirmer sont nommés, à un seul endroit."""

    def test_the_two_open_choices_are_named_constants(self):
        self.assertIn(
            macos_install.INSTALL_MODE, (macos_desktop.LAUNCH_EXEC, macos_desktop.LAUNCH_CHILD)
        )
        self.assertTrue(macos_install.INSTALL_IDENTITY)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang")
                     and shutil.which("codesign"), "requires native macOS signing tools")
class NativeBundleSignatureTest(unittest.TestCase):
    """Actual clang/codesign validation; never starts the app or requests TCC."""

    def test_locale_stability_and_sealed_localizations(self):
        with tempfile.TemporaryDirectory(prefix="aparte-native-bundle-") as folder:
            root = Path(folder)
            bundles = []
            for locale in ("fr_CA.UTF-8", "en_US.UTF-8"):
                staging = root / locale
                staging.mkdir()
                with mock.patch.dict(os.environ, {"LANG": locale, "LC_ALL": locale,
                                                  "LC_MESSAGES": locale}):
                    bundles.append(macos_install._build(
                        staging, sys.executable, macos_desktop.LAUNCH_EXEC, "-"))
            for relative in ("Contents/MacOS/aparte", "Contents/Info.plist"):
                self.assertEqual((bundles[0] / relative).read_bytes(),
                                 (bundles[1] / relative).read_bytes())
            fingerprint = macos_install.read_cdhash(bundles[0])
            self.assertIsNotNone(fingerprint)
            self.assertEqual(fingerprint, macos_install.read_cdhash(bundles[1]))
            localized = bundles[0] / "Contents/Resources/fr.lproj/InfoPlist.strings"
            localized.write_text("tampered synthetic resource", encoding="utf-8")
            with self.assertRaises(macos_install.InstallError):
                macos_install._verify_signature(bundles[0])
