import sys
import unittest
from unittest import mock

from aparte import macos_insert
from aparte.clipboard import ClipboardError


class FakeQuartz:
    """Records the CGEvent calls, the way a real Mac never lets us here. The
    mocked tests lock the observable contract — which events we build and post —
    not the on-screen effect, which is an M8 concern."""

    def __init__(self, event_factory=None):
        self.kCGEventFlagMaskCommand = 1 << 20
        self.kCGHIDEventTap = 0
        self.created = []  # (keycode, keydown)
        self.flagged = []  # (event, flags)
        self.unicode = []  # (event, length, string)
        self.posted = []  # (tap, event)
        self._factory = event_factory or (lambda keycode, keydown: {"keycode": keycode, "keydown": keydown})

    def CGEventCreateKeyboardEvent(self, source, keycode, keydown):
        self.created.append((keycode, keydown))
        return self._factory(keycode, keydown)

    def CGEventSetFlags(self, event, flags):
        self.flagged.append((event, flags))

    def CGEventKeyboardSetUnicodeString(self, event, length, string):
        self.unicode.append((event, length, string))

    def CGEventPost(self, tap, event):
        self.posted.append((tap, event))


def _with_quartz(quartz):
    return mock.patch.dict(sys.modules, {"Quartz": quartz})


class InsertViaPasteTest(unittest.TestCase):
    def test_it_posts_a_command_v_down_and_up(self):
        quartz = FakeQuartz()
        with _with_quartz(quartz):
            backend = macos_insert.insert_via_paste()
        self.assertEqual(backend, "cgevent-paste")
        # kVK_ANSI_V is 9; one key-down then one key-up.
        self.assertEqual(quartz.created, [(9, True), (9, False)])
        # Both carry the Command modifier — that is what makes it Cmd+V.
        self.assertTrue(all(flags == quartz.kCGEventFlagMaskCommand for _e, flags in quartz.flagged))
        self.assertEqual(len(quartz.flagged), 2)
        # Both are posted to the HID tap.
        self.assertEqual(len(quartz.posted), 2)
        self.assertTrue(all(tap == quartz.kCGHIDEventTap for tap, _e in quartz.posted))

    def test_a_missing_quartz_raises_rather_than_no_op(self):
        # sys.modules[name] = None makes `import name` raise ImportError.
        with _with_quartz(None):
            with self.assertRaises(ClipboardError):
                macos_insert.insert_via_paste()

    def test_a_none_event_raises_rather_than_silently_succeed(self):
        quartz = FakeQuartz(event_factory=lambda keycode, keydown: None)
        with _with_quartz(quartz):
            with self.assertRaises(ClipboardError):
                macos_insert.insert_via_paste()
        # Nothing was posted — no silent success.
        self.assertEqual(quartz.posted, [])


class TypeUnicodeTest(unittest.TestCase):
    def test_it_preserves_a_long_french_string_and_its_critical_characters(self):
        # Curly apostrophe, guillemets and a non-breaking space are exactly the
        # French characters osascript keystroke would mangle — they must survive.
        text = "L’élève répondit : « oui »." + " bonjour tout le monde, " * 5
        quartz = FakeQuartz()
        with _with_quartz(quartz):
            backend = macos_insert.type_unicode(text)
        self.assertEqual(backend, "cgevent-type")
        chunks = [chunk for _event, _length, chunk in quartz.unicode]
        # The concatenated chunks reproduce the string exactly, nothing dropped.
        self.assertEqual("".join(chunks), text)
        # Each event's declared length matches the chunk it carries.
        self.assertTrue(all(length == len(chunk) for _e, length, chunk in quartz.unicode))
        # The chunking stays bounded.
        self.assertTrue(all(len(chunk) <= macos_insert._UNICODE_CHUNK for chunk in chunks))
        # The critical characters are present in the posted text.
        self.assertIn("’", "".join(chunks))
        self.assertIn("« oui »", "".join(chunks))
        self.assertIn(" ", "".join(chunks))
        # As many posts as chunks.
        self.assertEqual(len(quartz.posted), len(chunks))

    def test_a_missing_quartz_raises(self):
        with _with_quartz(None):
            with self.assertRaises(ClipboardError):
                macos_insert.type_unicode("bonjour")


if __name__ == "__main__":
    unittest.main()
