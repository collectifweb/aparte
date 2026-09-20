"""The documented test entry point must not inherit a personal installation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-tests.py"
spec = importlib.util.spec_from_file_location("aparte_test_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class IsolatedRunnerTest(unittest.TestCase):
    def test_personal_overrides_are_removed_before_starting_python(self):
        inherited = {
            "APARTE_CONFIG": "/personal/config.json",
            "APARTE_RUNTIME_DIR": "/personal/runtime",
            "APARTE_HISTORY_PERSIST": "true",
            "MURMUR_RUNTIME_DIR": "/legacy/runtime",
            "MURMUR_MODEL": "/personal/model",
            "PYTHONPATH": "/personal/modules",
            "PATH": "/usr/bin",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = runner.isolated_environment(root, inherited)
            for name in ("APARTE_RUNTIME_DIR", "APARTE_HISTORY_PERSIST",
                         "MURMUR_RUNTIME_DIR", "MURMUR_MODEL"):
                self.assertNotIn(name, environment)
            self.assertEqual(environment["APARTE_CONFIG"], str(root / "config/aparte/config.json"))
            self.assertEqual(environment["PATH"], "/usr/bin")
            self.assertNotIn("/personal/modules", environment["PYTHONPATH"])
            for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME",
                         "XDG_RUNTIME_DIR", "XDG_CACHE_HOME", "HF_HOME", "HF_HUB_CACHE",
                         "HUGGINGFACE_HUB_CACHE", "TORCH_HOME", "TMPDIR"):
                location = Path(environment[name])
                self.assertTrue(location.is_relative_to(root), name)
                self.assertTrue(location.is_dir(), name)
            self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
            self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertEqual(inherited["APARTE_CONFIG"], "/personal/config.json")

    def test_full_discovery_preserves_the_tests_top_level(self):
        command = runner.test_command("all", [])
        self.assertEqual(command[-6:], ["discover", "-s", "tests", "-t", "tests", "-v"])

    def test_explicit_selection_remains_available_for_local_verification(self):
        command = runner.test_command("all", ["test_model_download"])
        self.assertEqual(command[-2:], ["-v", "test_model_download"])

    def test_native_selection_contains_actual_signature_validation(self):
        self.assertIn("test_macos_install", runner.MACOS_TESTS)
        self.assertNotIn("test_clipboard", runner.MACOS_TESTS)
        self.assertIn("test_clipboard.PasteMacTest", runner.MACOS_TESTS)
