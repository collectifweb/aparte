"""M7a — the macOS application bundle, proved without a Mac.

Everything here is string and path work, so it runs on the Linux dev machine. What these
tests cannot prove — that macOS really attributes the permission to the bundle, that
``codesign`` accepts the result — is measured by the M7-0 probe on a real Mac.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import macos_desktop


class StableInterpreterTest(unittest.TestCase):
    """The launcher must name a path that survives ``brew upgrade``."""

    def test_cellar_path_becomes_the_version_stable_opt_path(self):
        self.assertEqual(
            macos_desktop.stable_interpreter(
                "/opt/homebrew/Cellar/aparte/1.1.1/libexec/bin/python3"
            ),
            "/opt/homebrew/opt/aparte/libexec/bin/python3",
        )

    def test_intel_prefix_is_rewritten_too(self):
        self.assertEqual(
            macos_desktop.stable_interpreter(
                "/usr/local/Cellar/aparte/2.0.0/libexec/bin/python3.12"
            ),
            "/usr/local/opt/aparte/libexec/bin/python3.12",
        )

    def test_two_versions_of_the_same_formula_give_the_same_path(self):
        # The whole point: an upgrade must not change what the launcher names, or the
        # bundle would have to be rewritten and the granted permissions would be lost.
        first = macos_desktop.stable_interpreter(
            "/opt/homebrew/Cellar/aparte/1.1.1/libexec/bin/python3"
        )
        second = macos_desktop.stable_interpreter(
            "/opt/homebrew/Cellar/aparte/9.9.9/libexec/bin/python3"
        )
        self.assertEqual(first, second)

    def test_a_plain_virtualenv_is_left_alone(self):
        path = "/home/alexandre/Apps-coding/Murmur/.venv/bin/python3"
        self.assertEqual(macos_desktop.stable_interpreter(path), path)

    def test_a_system_interpreter_is_left_alone(self):
        self.assertEqual(macos_desktop.stable_interpreter("/usr/bin/python3"), "/usr/bin/python3")

    def test_a_truncated_cellar_path_is_left_alone(self):
        # Nothing to rewrite and nothing to guess: better untouched than mangled.
        path = "/opt/homebrew/Cellar/aparte"
        self.assertEqual(macos_desktop.stable_interpreter(path), path)


class InfoPlistTest(unittest.TestCase):
    def setUp(self):
        self.document = plistlib.loads(macos_desktop.build_info_plist("fr"))

    def test_identity_keys(self):
        self.assertEqual(self.document["CFBundleIdentifier"], "ca.collectifweb.aparte")
        self.assertEqual(self.document["CFBundleName"], "Aparté")
        self.assertEqual(self.document["CFBundleExecutable"], macos_desktop.LAUNCHER_NAME)
        self.assertEqual(self.document["CFBundlePackageType"], "APPL")

    def test_no_dock_icon(self):
        # Aparté is a menu-bar resident (M6), not a windowed application.
        self.assertIs(self.document["LSUIElement"], True)

    def test_microphone_reason_has_a_stable_fallback_and_declares_localizations(self):
        # Without this key macOS kills the process instead of asking.
        self.assertIn("Aparté", self.document["NSMicrophoneUsageDescription"])
        english = plistlib.loads(macos_desktop.build_info_plist("en"))
        self.assertEqual(
            english["NSMicrophoneUsageDescription"],
            self.document["NSMicrophoneUsageDescription"],
        )
        self.assertEqual(self.document["CFBundleLocalizations"], ["fr", "en"])

    def test_the_version_is_the_launchers_not_apartes(self):
        # The bundle must not move when Aparté is released, or the cdhash changes and
        # macOS forgets every granted permission — silently, checkbox still ticked.
        from aparte import __version__

        self.assertEqual(
            self.document["CFBundleShortVersionString"], macos_desktop.LAUNCHER_VERSION
        )
        self.assertNotIn(__version__, macos_desktop.build_info_plist("fr").decode("utf-8"))


class LauncherSourceTest(unittest.TestCase):
    def test_it_names_the_interpreter_it_was_given(self):
        source = macos_desktop.launcher_source("/opt/homebrew/opt/aparte/libexec/bin/python3")
        self.assertIn('"/opt/homebrew/opt/aparte/libexec/bin/python3"', source)

    def test_it_launches_the_desktop_server(self):
        source = macos_desktop.launcher_source("/x/python3")
        self.assertIn('"-m"', source)
        self.assertIn('"aparte"', source)
        self.assertIn('"desktop"', source)

    def test_custom_arguments_are_baked_in(self):
        # The M7-0 probe runs its own script rather than the server.
        source = macos_desktop.launcher_source("/x/python3", args=("/tmp/probe.py", "--mic"))
        self.assertIn('"/tmp/probe.py"', source)
        self.assertIn('"--mic"', source)
        self.assertNotIn('"desktop"', source)

    def test_it_checks_the_interpreter_before_using_it(self):
        # A bundle that dies from Finder leaves no trace; it has to say something.
        source = macos_desktop.launcher_source("/x/python3")
        self.assertIn("stat(kInterpreter", source)
        self.assertIn("show_error", source)
        self.assertIn("osascript", source)

    def test_exec_mode_replaces_the_process(self):
        source = macos_desktop.launcher_source("/x/python3", mode=macos_desktop.LAUNCH_EXEC)
        self.assertIn("execv(kInterpreter", source)
        self.assertNotIn("waitpid(child", source)

    def test_child_mode_keeps_the_bundle_executable_alive(self):
        source = macos_desktop.launcher_source("/x/python3", mode=macos_desktop.LAUNCH_CHILD)
        self.assertIn("posix_spawn(&child", source)
        self.assertIn("waitpid(child", source)
        # Signals have to reach Python, or "Quit" would leave a recorder running.
        self.assertIn("forward_signal", source)

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            macos_desktop.launcher_source("/x/python3", mode="magic")

    def test_it_carries_nothing_that_varies_with_the_clock(self):
        # __DATE__/__TIME__ would make every compile produce a different binary, hence a
        # different cdhash, hence permissions lost on any reinstall.
        source = macos_desktop.launcher_source("/x/python3")
        self.assertNotIn("__DATE__", source)
        self.assertNotIn("__TIME__", source)

    def test_a_quote_in_the_path_cannot_break_out_of_the_literal(self):
        source = macos_desktop.launcher_source('/x/we"ird/python3')
        self.assertIn(r'"/x/we\"ird/python3"', source)


@unittest.skipIf(shutil.which("cc") is None, "no C compiler on this machine")
class LauncherCompilesTest(unittest.TestCase):
    """The generated C must actually compile — a string test cannot see a missing header.

    Written after the first version shipped a ``snprintf`` call without ``<stdio.h>``:
    an implicit function declaration, which recent clang treats as an **error**, so
    ``aparte install-app`` would have failed on any current Mac. Compiled here with the
    local compiler, which proves the syntax and the includes; the macOS-specific
    behaviour is still M7-0's job.
    """

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def _compile(self, mode: str) -> subprocess.CompletedProcess:
        source = self.root / f"launcher-{mode}.c"
        source.write_text(
            macos_desktop.launcher_source("/opt/homebrew/opt/aparte/libexec/bin/python3",
                                          mode=mode, language="fr"),
            encoding="utf-8",
        )
        return subprocess.run(
            ["cc", "-O2", "-g0", "-fno-common", "-Wall", "-Wextra",
             "-o", str(self.root / mode), str(source)],
            capture_output=True,
            text=True,
        )

    def test_exec_variant_compiles_without_warnings(self):
        result = self._compile(macos_desktop.LAUNCH_EXEC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), "", result.stderr)

    def test_child_variant_compiles_without_warnings(self):
        result = self._compile(macos_desktop.LAUNCH_CHILD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), "", result.stderr)


class LauncherRunsTest(unittest.TestCase):
    """Compiling proves the syntax; running proves the two variants are actually
    different things — which is the whole question M7-0 puts to a Mac.

    ``exec`` replaces the launcher's image, so by the time the interpreter asks for
    a permission the bundle's executable no longer exists as a process. ``child``
    keeps it alive as the parent — the unambiguous case — and pays for it in signal
    forwarding. Both facts are observable here; only macOS's *attribution* is not.
    """

    def setUp(self):
        if shutil.which("cc") is None:
            self.skipTest("no C compiler on this machine")
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def _build(self, mode, *args):
        source = self.root / f"{mode}.c"
        source.write_text(
            macos_desktop.launcher_source(sys.executable, mode=mode, language="fr", args=args),
            encoding="utf-8",
        )
        binary = self.root / mode
        subprocess.run(
            ["cc", "-O2", "-g0", "-fno-common", "-o", str(binary), str(source)],
            capture_output=True, text=True, check=True,
        )
        return binary

    def _parent_of_the_interpreter(self, mode):
        script = self.root / "who.py"
        script.write_text("import os\nprint(os.getppid())\n", encoding="utf-8")
        launcher = self._build(mode, str(script))
        done = subprocess.run([str(launcher)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return int(done.stdout.strip())

    def test_exec_hands_its_own_process_over_to_the_interpreter(self):
        # No launcher process is left: the interpreter's parent is whoever ran us.
        self.assertEqual(self._parent_of_the_interpreter(macos_desktop.LAUNCH_EXEC), os.getpid())

    def test_child_stays_alive_as_the_parent(self):
        # A live process whose executable sits inside the bundle — the case macOS
        # cannot misread, if the exec variant turns out not to be enough.
        self.assertNotEqual(self._parent_of_the_interpreter(macos_desktop.LAUNCH_CHILD), os.getpid())

    def test_the_child_variant_forwards_the_signals_it_receives(self):
        # This is what the variant costs. Left out, quitting Aparté would leave the
        # interpreter — and on a Mac, an open microphone — behind.
        script = self.root / "sleeper.py"
        script.write_text(
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, lambda *a: sys.exit(7))\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        launcher = self._build(macos_desktop.LAUNCH_CHILD, str(script))
        process = subprocess.Popen([str(launcher)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(process.kill)
        self.assertEqual(process.stdout.readline().strip(), "ready")
        children = subprocess.run(
            ["pgrep", "-P", str(process.pid)], capture_output=True, text=True
        ).stdout.split()
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=10)
        self.assertFalse(
            [pid for pid in children if Path(f"/proc/{pid}").exists()],
            "the interpreter outlived the launcher that was signalled",
        )


class CompileCommandTest(unittest.TestCase):
    def test_options_are_fixed_and_carry_no_debug_paths(self):
        command = macos_desktop.clang_command(Path("/tmp/a.c"), Path("/tmp/a"))
        self.assertEqual(command[0], "clang")
        self.assertIn("-g0", command)  # debug info would embed temporary paths
        self.assertIn("-O2", command)
        self.assertIn(f"-mmacosx-version-min={macos_desktop.MACOSX_DEPLOYMENT_TARGET}", command)

    def test_deployment_target_is_pinned_not_inherited(self):
        # Inheriting the SDK default would make the binary depend on the machine's Xcode.
        self.assertTrue(
            any(part.startswith("-mmacosx-version-min=") for part in macos_desktop.CLANG_OPTIONS)
        )

    def test_signing_is_ad_hoc_with_a_pinned_identifier(self):
        command = macos_desktop.codesign_command(Path("/x/Aparté.app"))
        self.assertEqual(command[0], "codesign")
        self.assertIn("--sign", command)
        self.assertIn("-", command)
        self.assertIn("--identifier", command)
        self.assertIn(macos_desktop.BUNDLE_IDENTIFIER, command)


class WriteBundleTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def _write(self, destination: Path) -> dict[str, Path]:
        return macos_desktop.write_bundle(
            destination, "/opt/homebrew/opt/aparte/libexec/bin/python3", language="fr"
        )

    def test_it_lays_out_the_expected_tree(self):
        paths = self._write(self.root / "Aparté.app")
        self.assertTrue(paths["plist"].is_file())
        self.assertTrue(paths["source"].is_file())
        self.assertEqual(paths["executable"].parent.name, "MacOS")
        self.assertEqual(paths["plist"].parent.name, "Contents")

    def test_the_bundle_is_byte_identical_across_two_apparte_versions(self):
        # The invariant the whole lot rests on. If this ever fails, macOS forgets the
        # granted permissions on upgrade — and says nothing, because the checkbox in
        # System Settings stays ticked.
        import aparte

        first = self.root / "first.app"
        self._write(first)
        original = aparte.__version__
        try:
            aparte.__version__ = "99.99.99"
            second = self.root / "second.app"
            self._write(second)
        finally:
            aparte.__version__ = original

        for name in ("Contents/Info.plist", "Contents/aparte.c"):
            self.assertEqual(
                (first / name).read_bytes(),
                (second / name).read_bytes(),
                f"{name} changed with the Aparté version",
            )

    def test_writing_twice_over_itself_is_stable(self):
        # install-app is idempotent, so a repair must not churn the bundle.
        destination = self.root / "Aparté.app"
        self._write(destination)
        before = (destination / "Contents" / "Info.plist").read_bytes()
        self._write(destination)
        self.assertEqual(before, (destination / "Contents" / "Info.plist").read_bytes())

    def test_localized_privacy_reasons_ship_together(self):
        bundle = self.root / "Aparté.app"
        self._write(bundle)
        for locale in ("fr", "en"):
            resource = bundle / "Contents" / "Resources" / f"{locale}.lproj" / "InfoPlist.strings"
            self.assertEqual(plistlib.loads(resource.read_bytes())["NSMicrophoneUsageDescription"],
                             macos_desktop.MICROPHONE_REASON[locale])

    def test_locale_never_changes_the_signed_sources_or_resources(self):
        trees = []
        for locale in ("fr_CA.UTF-8", "en_US.UTF-8"):
            bundle = self.root / f"{locale}.app"
            with mock.patch.dict(os.environ, {"LANG": locale, "LC_ALL": locale,
                                              "LC_MESSAGES": locale}):
                macos_desktop.write_bundle(bundle, "/stable/python")
            trees.append({str(path.relative_to(bundle)): path.read_bytes()
                          for path in bundle.rglob("*") if path.is_file()})
        self.assertEqual(trees[0], trees[1])
        self.assertEqual(macos_desktop.launcher_source("/stable/python", language="fr"),
                         macos_desktop.launcher_source("/stable/python", language="en"))

    def test_a_missing_icon_does_not_stop_the_bundle(self):
        # The .icns lands in M7b; until then the bundle still has to be buildable.
        paths = self._write(self.root / "Aparté.app")
        self.assertTrue(paths["icon"].parent.is_dir())


class IconTest(unittest.TestCase):
    """The committed ``.icns`` — a contributor must never have to build it.

    Assembled on Linux by ``scripts/build-icns.py`` because ``iconutil`` and ``sips``
    are macOS tools and there is no Mac here. The container is simple enough to check
    by hand: a magic word, a total length, then one length-prefixed PNG per slot.
    """

    @classmethod
    def setUpClass(cls):
        cls.path = macos_desktop.ASSETS_DIR / macos_desktop.ICON_FILE
        cls.data = cls.path.read_bytes() if cls.path.exists() else b""

    def _slots(self):
        offset, found = 8, {}
        while offset < len(self.data):
            ostype, length = struct.unpack(">4sI", self.data[offset : offset + 8])
            payload = self.data[offset + 8 : offset + length]
            found[ostype.decode("ascii")] = payload
            offset += length
        return found

    def test_it_is_committed(self):
        self.assertTrue(self.path.is_file(), f"{self.path} is missing — run scripts/build-icns.py")

    def test_header_declares_the_real_length(self):
        # A wrong length is the one corruption macOS refuses silently: no icon, no error.
        magic, total = struct.unpack(">4sI", self.data[:8])
        self.assertEqual(magic, b"icns")
        self.assertEqual(total, len(self.data))

    def test_every_slot_holds_a_png_of_the_declared_size(self):
        for ostype, payload in self._slots().items():
            self.assertEqual(payload[:4], b"\x89PNG", f"{ostype} is not a PNG")
            width, height = struct.unpack(">II", payload[16:24])
            self.assertEqual(width, height, f"{ostype} is not square")

    def test_both_the_retina_and_non_retina_slots_are_filled(self):
        # macOS picks by slot, never by measuring: a missing @2x makes Retina upscale.
        slots = self._slots()
        for ostype in ("ic07", "ic08", "ic09", "ic10", "ic11", "ic12", "ic13", "ic14"):
            self.assertIn(ostype, slots)

    def test_the_mark_keeps_apples_margin(self):
        # 824 of 1024 — the margin is what aligns Aparté optically with every other
        # icon in the Dock and in the System Settings list. Filling the canvas would
        # make it visibly bigger than its neighbours, which reads as "not a real Mac
        # app" exactly where the permission model is supposed to look trustworthy.
        source = (macos_desktop.ASSETS_DIR / "aparte-app.svg").read_text(encoding="utf-8")
        self.assertIn('viewBox="0 0 1024 1024"', source)
        self.assertIn("scale(1.7166667)", source)  # 480 → 824


class ApplicationsDirTest(unittest.TestCase):
    def test_the_bundle_lives_outside_the_homebrew_prefix(self):
        # Inside the prefix, brew upgrade would rebuild it — a new cdhash every release.
        self.assertEqual(macos_desktop.applications_dir().name, "Applications")
        self.assertEqual(macos_desktop.bundle_path().name, macos_desktop.BUNDLE_NAME)
        self.assertNotIn("Cellar", str(macos_desktop.bundle_path()))


if __name__ == "__main__":
    unittest.main()
