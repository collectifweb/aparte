import unittest
from unittest import mock

from aparte import linux_desktop, platform_dispatch
from aparte.platform_dispatch import (
    UnsupportedPlatformError,
    desktop_integration,
    is_linux,
    is_macos,
)


def _as(platform_name: str):
    """Pretend we run on ``platform_name`` for the duration of the block.

    Detection reads ``sys.platform`` at call time, so patching the module's view
    of it is what proves the classification — not a stale module-level flag.
    """
    return mock.patch.object(platform_dispatch.sys, "platform", platform_name)


class PlatformClassificationTest(unittest.TestCase):
    def test_linux_is_linux(self):
        with _as("linux"):
            self.assertTrue(is_linux())
            self.assertFalse(is_macos())

    def test_old_linux2_still_counts_as_linux(self):
        with _as("linux2"):
            self.assertTrue(is_linux())
            self.assertFalse(is_macos())

    def test_darwin_is_macos(self):
        with _as("darwin"):
            self.assertTrue(is_macos())
            self.assertFalse(is_linux())

    def test_other_unix_is_neither(self):
        with _as("freebsd13"):
            self.assertFalse(is_linux())
            self.assertFalse(is_macos())


class DesktopIntegrationTest(unittest.TestCase):
    def test_linux_returns_the_existing_module(self):
        with _as("linux"):
            self.assertIs(desktop_integration(), linux_desktop)

    def test_macos_raises_without_importing_a_macos_module(self):
        # The raise must come from the guard, not from a failed import of a
        # macos_* module that does not exist yet: an UnsupportedPlatformError
        # (not ModuleNotFoundError) is exactly that proof.
        with _as("darwin"):
            with self.assertRaises(UnsupportedPlatformError):
                desktop_integration()

    def test_other_unix_also_raises(self):
        with _as("freebsd13"):
            with self.assertRaises(UnsupportedPlatformError):
                desktop_integration()

    def test_message_is_actionable(self):
        with _as("darwin"):
            with self.assertRaises(UnsupportedPlatformError) as caught:
                desktop_integration()
        message = str(caught.exception)
        self.assertIn("Linux only", message)
        self.assertIn("aparte desktop", message)


if __name__ == "__main__":
    unittest.main()
