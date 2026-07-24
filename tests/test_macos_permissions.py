import sys
import unittest
from unittest import mock

from aparte import macos_permissions


class MicrophoneAuthorizationTest(unittest.TestCase):
    """AVFoundation returns an int enum; we translate it to a stable string and
    never let a missing framework or a surprise value raise."""

    def _with_avfoundation(self, status):
        fake = mock.Mock()
        fake.AVMediaTypeAudio = "soun"
        fake.AVCaptureDevice.authorizationStatusForMediaType_.return_value = status
        return mock.patch.dict(sys.modules, {"AVFoundation": fake})

    def test_each_status_maps_to_its_name(self):
        for value, name in [(0, "not_determined"), (1, "restricted"), (2, "denied"), (3, "authorized")]:
            with self._with_avfoundation(value):
                self.assertEqual(macos_permissions.microphone_authorization(), name)

    def test_an_unexpected_value_is_unknown(self):
        with self._with_avfoundation(99):
            self.assertEqual(macos_permissions.microphone_authorization(), "unknown")

    def test_a_missing_framework_is_unknown_not_an_error(self):
        # sys.modules[name] = None makes `import name` raise ImportError.
        with mock.patch.dict(sys.modules, {"AVFoundation": None}):
            self.assertEqual(macos_permissions.microphone_authorization(), "unknown")


class AccessibilityTrustedTest(unittest.TestCase):
    """AXIsProcessTrusted reads without prompting; unknown maps to None, never a raise."""

    def _with_appservices(self, trusted):
        fake = mock.Mock()
        fake.AXIsProcessTrusted.return_value = trusted
        return mock.patch.dict(sys.modules, {"ApplicationServices": fake})

    def test_trusted_is_true(self):
        with self._with_appservices(True):
            self.assertIs(macos_permissions.accessibility_trusted(), True)

    def test_untrusted_is_false(self):
        with self._with_appservices(False):
            self.assertIs(macos_permissions.accessibility_trusted(), False)

    def test_a_missing_framework_is_none_not_an_error(self):
        with mock.patch.dict(sys.modules, {"ApplicationServices": None, "HIServices": None}):
            self.assertIsNone(macos_permissions.accessibility_trusted())


if __name__ == "__main__":
    unittest.main()
