import unittest

from whispr_flow_linux.desktop import DESKTOP_HTML


class DesktopHtmlTest(unittest.TestCase):
    def test_browser_recording_encodes_wav(self):
        self.assertIn("startWavRecording", DESKTOP_HTML)
        self.assertIn('type: "audio/wav"', DESKTOP_HTML)
        self.assertIn('writeAscii(view, 8, "WAVE")', DESKTOP_HTML)
        self.assertNotIn("new MediaRecorder", DESKTOP_HTML)


if __name__ == "__main__":
    unittest.main()
