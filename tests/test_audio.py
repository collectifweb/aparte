import subprocess
import unittest
from pathlib import Path
from unittest import mock

from aparte import audio

ARECORD_L = """null
    Discard all samples (playback) or generate zero samples (capture)
pipewire
    PipeWire Sound Server
default
    Default ALSA Output (currently PipeWire Media Server)
hw:CARD=camera,DEV=0
    web camera, USB Audio
    Direct hardware device without any conversions
plughw:CARD=camera,DEV=0
    web camera, USB Audio
    Hardware device with all software conversions
plughw:CARD=Mini,DEV=0
    Razer Seiren Mini, USB Audio
    Hardware device with all software conversions
"""


class ListMicrophonesTest(unittest.TestCase):
    def _listing(self, stdout):
        return mock.patch.object(
            audio.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout=stdout, stderr=""),
        )

    def test_only_the_devices_that_can_resample_are_offered(self):
        """Whisper wants 16 kHz; a raw `hw:` device would refuse it outright."""
        with mock.patch.object(audio.shutil, "which", return_value="/usr/bin/arecord"):
            with self._listing(ARECORD_L):
                devices = audio.list_microphones()
        self.assertEqual(
            devices,
            [
                {"name": "plughw:CARD=camera,DEV=0", "label": "web camera, USB Audio"},
                {"name": "plughw:CARD=Mini,DEV=0", "label": "Razer Seiren Mini, USB Audio"},
            ],
        )

    def test_no_arecord_means_an_empty_list_rather_than_an_error(self):
        with mock.patch.object(audio.shutil, "which", return_value=None):
            self.assertEqual(audio.list_microphones(), [])


class RecordDeviceTest(unittest.TestCase):
    def test_the_chosen_microphone_is_passed_to_arecord(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(audio.subprocess, "run", return_value=completed) as run:
            audio._record_wav_arecord(2.0, 16000, "plughw:CARD=Mini,DEV=0")
        command = run.call_args.args[0]
        self.assertIn("-D", command)
        self.assertEqual(command[command.index("-D") + 1], "plughw:CARD=Mini,DEV=0")

    def test_no_microphone_chosen_leaves_the_command_untouched(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(audio.subprocess, "run", return_value=completed) as run:
            audio._record_wav_arecord(2.0, 16000)
        self.assertNotIn("-D", run.call_args.args[0])

    def test_a_chosen_microphone_routes_auto_to_arecord(self):
        """The name comes from ALSA, and arecord is the backend that speaks it —
        which also keeps this path on the same device as the global shortcut."""
        with mock.patch.object(audio.shutil, "which", return_value="/usr/bin/arecord"):
            with mock.patch.object(audio, "_record_wav_arecord") as arecord:
                with mock.patch.object(audio, "_record_wav_sounddevice") as sounddevice:
                    audio.record_wav(2.0, device="plughw:CARD=Mini,DEV=0")
        sounddevice.assert_not_called()
        arecord.assert_called_once_with(2.0, 16000, "plughw:CARD=Mini,DEV=0")


class BeepTest(unittest.TestCase):
    def test_the_tone_is_a_playable_wav(self):
        import wave

        path = audio._beep_file("start", audio.BEEP_TONES["start"])
        self.addCleanup(path.unlink, True)
        with wave.open(str(path), "rb") as handle:
            self.assertEqual(handle.getnchannels(), 1)
            self.assertGreater(handle.getnframes(), 0)

    def test_an_unknown_kind_plays_nothing(self):
        with mock.patch.object(audio.subprocess, "run") as run:
            audio.play_beep("whatever")
        run.assert_not_called()

    def test_a_missing_player_is_not_an_error(self):
        with mock.patch.object(audio.shutil, "which", return_value=None):
            self.assertIsNone(audio.play_beep("start"))


class MacBackendTest(unittest.TestCase):
    """macOS speaks afplay and PortAudio, never ALSA/arecord."""

    def test_beep_plays_through_afplay(self):
        with mock.patch.object(audio, "is_macos", return_value=True):
            with mock.patch.object(audio.shutil, "which", return_value="/usr/bin/afplay"):
                with mock.patch.object(audio, "_beep_file", return_value=Path("/tmp/beep.wav")):
                    with mock.patch.object(audio.subprocess, "run") as run:
                        audio.play_beep("start")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "afplay")
        self.assertNotIn("-q", command)  # -q is an aplay flag, not an afplay one

    def test_microphones_come_from_portaudio_as_names(self):
        fake_sd = mock.Mock()
        fake_sd.query_devices.return_value = [
            {"name": "MacBook Pro Microphone", "max_input_channels": 1},
            {"name": "MacBook Pro Speakers", "max_input_channels": 0},
            {"name": "USB Mic", "max_input_channels": 2},
        ]
        with mock.patch.object(audio, "is_macos", return_value=True):
            with mock.patch.dict("sys.modules", {"sounddevice": fake_sd}):
                devices = audio.list_microphones()
        self.assertEqual(
            devices,
            [
                {"name": "MacBook Pro Microphone", "label": "MacBook Pro Microphone"},
                {"name": "USB Mic", "label": "USB Mic"},
            ],
        )

    def test_missing_portaudio_is_an_empty_list_not_an_error(self):
        # sys.modules["sounddevice"] = None makes `import sounddevice` raise.
        with mock.patch.object(audio, "is_macos", return_value=True):
            with mock.patch.dict("sys.modules", {"sounddevice": None}):
                self.assertEqual(audio.list_microphones(), [])

    def test_record_wav_uses_sounddevice_and_never_arecord(self):
        with mock.patch.object(audio, "is_macos", return_value=True):
            with mock.patch.object(audio, "_record_wav_sounddevice") as sounddevice:
                with mock.patch.object(audio, "_record_wav_arecord") as arecord:
                    audio.record_wav(2.0, device="USB Mic")
        sounddevice.assert_called_once_with(2.0, 16000, "USB Mic")
        arecord.assert_not_called()


if __name__ == "__main__":
    unittest.main()
