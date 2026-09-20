import builtins
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from aparte import model_download, diagnostics
from aparte.config import Settings


def populate(repo, revision="abc", complete=True):
    root = model_download.repo_dir(repo)
    (root / "refs").mkdir(parents=True, exist_ok=True)
    (root / "refs" / "main").write_text(revision)
    folder = root / "snapshots" / revision
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.json"):
        if complete or name != "model.bin":
            (folder / name).write_bytes(b"synthetic")
    return folder


class ModelTest(unittest.TestCase):
    def setUp(self):
        model_download.reset_for_tests()
        self.addCleanup(model_download.reset_for_tests)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HF_HUB_CACHE": self.tmp.name, "HF_HOME": "",
            "HUGGINGFACE_HUB_CACHE": "", "XDG_CACHE_HOME": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.settings = Settings(model="small", transcriber="faster-whisper")
        self.repo = "Systran/faster-whisper-small"

    def test_aliases_follow_real_repositories(self):
        for name, repo in {"small": self.repo, "large": "Systran/faster-whisper-large-v3",
            "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
            "org/custom": "org/custom"}.items():
            self.assertEqual(model_download.repo_id(name), repo)
        self.assertIsNone(model_download.repo_id("unknown"))
        self.assertIsNone(model_download.repo_id(""))
        self.assertIsNone(model_download.repo_id(self.tmp.name))
        self.assertIsNone(model_download.repo_id("/absent/local/model"))

    def test_installed_backend_alias_table_wins(self):
        with mock.patch.dict("sys.modules", {"faster_whisper.utils": mock.Mock(_MODELS={"future": "org/new"})}):
            self.assertEqual(model_download.repo_id("future"), "org/new")
            self.assertIsNone(model_download.repo_id("small"))

    def test_native_dependency_import_failure_does_not_abort_desktop_preparation(self):
        original_import = builtins.__import__

        def import_with_incompatible_engine(name, *args, **kwargs):
            if name == "faster_whisper.utils":
                raise OSError("dlopen: incompatible native library")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=import_with_incompatible_engine):
            self.assertEqual(model_download.repo_id("small"), self.repo)
            self.assertFalse(diagnostics._whisper_model_cached(self.settings))
            with mock.patch.object(model_download.threading, "Thread") as worker:
                model_download.start(self.settings)
        worker.assert_called_once()
        state = model_download.snapshot()
        self.assertEqual(state["state"], model_download.DOWNLOADING)
        self.assertEqual(state["repo"], self.repo)

    def test_empty_partial_and_wrong_repo_never_pass(self):
        (model_download.repo_dir(self.repo) / "snapshots").mkdir(parents=True)
        self.assertFalse(model_download.model_cached(self.settings))
        populate("Systran/faster-whisper-small.en")
        self.assertFalse(diagnostics._whisper_model_cached(self.settings))
        folder = populate(self.repo, complete=False)
        (folder / "model.bin").write_bytes(b"")
        self.assertFalse(model_download.model_cached(self.settings))
        (folder / "model.bin").unlink()
        (folder / "model.bin").symlink_to(folder / "missing")
        self.assertFalse(model_download.model_cached(self.settings))

    def test_only_default_revision_counts(self):
        populate(self.repo)
        (model_download.repo_dir(self.repo) / "refs" / "main").write_text("incomplete")
        self.assertFalse(model_download.model_cached(self.settings))

    def test_complete_exact_model_shared_by_diagnostics_and_download(self):
        populate(self.repo)
        self.assertTrue(diagnostics._whisper_model_cached(self.settings))
        with mock.patch.object(model_download.threading, "Thread") as worker:
            model_download.start(self.settings)
        worker.assert_not_called()
        self.assertEqual(model_download.snapshot()["state"], model_download.READY)

    def test_local_directory_needs_all_files(self):
        settings = Settings(model=self.tmp.name, transcriber="faster-whisper")
        self.assertFalse(model_download.ensure_ready(settings))
        for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
            (Path(self.tmp.name) / name).write_bytes(b"x")
        self.assertTrue(model_download.ensure_ready(settings))

    def test_cache_environment_precedence(self):
        for env, expected in [
            ({"HF_HUB_CACHE": "/hub", "HF_HOME": "/home"}, "/hub"),
            ({"HF_HUB_CACHE": "", "HUGGINGFACE_HUB_CACHE": "/legacy"}, "/legacy"),
            ({"HF_HUB_CACHE": "", "HF_HOME": "/hf"}, "/hf/hub"),
            ({"HF_HUB_CACHE": "", "XDG_CACHE_HOME": "/xdg"}, "/xdg/huggingface/hub"),
        ]:
            with mock.patch.dict(os.environ, env):
                self.assertEqual(model_download.cache_root(), Path(expected))

    def test_backends_do_not_reuse_an_unrelated_hub_model(self):
        populate(self.repo)
        for backend in ("openai-whisper", "whisper.cpp"):
            settings = Settings(model="small", transcriber=backend)
            with mock.patch.dict("sys.modules", {"whisper": None}):
                self.assertFalse(model_download.model_cached(settings))
                with mock.patch.object(model_download.threading, "Thread") as worker:
                    model_download.start(settings)
                worker.assert_not_called()
                self.assertEqual(model_download.snapshot()["state"], model_download.UNAVAILABLE)

    def test_auto_without_faster_whisper_does_not_download_unused_weights(self):
        with mock.patch.object(model_download, "_has_module", side_effect=lambda name: name == "whisper"), mock.patch.dict("sys.modules", {"whisper": None}), mock.patch.object(model_download.threading, "Thread") as worker:
            model_download.start(Settings(model="small", transcriber="auto"))
            worker.assert_not_called()
            self.assertEqual(model_download.snapshot()["reason"], "backend")

    def test_named_openai_partial_checkpoint_is_never_announced_ready(self):
        folder = Path(self.tmp.name) / "whisper"
        folder.mkdir()
        (folder / "small.pt").write_bytes(b"partial checkpoint")
        self.assertFalse(model_download.model_cached(Settings(model="small", transcriber="openai-whisper")))

    def test_reading_before_application_start_remains_absent(self):
        self.assertIsNone(model_download.progress(self.settings))

    def test_unavailable_backend_and_new_config_clear_previous_repo_error(self):
        model_download._set(state="error", repo=self.repo, error="old error", model="small")
        model_download.start(Settings(model="small", transcriber="whisper.cpp"))
        state = model_download.progress()
        self.assertIsNone(state["error"])
        self.assertNotIn("repo", state)

    def test_observing_config_change_never_downloads_or_returns_old_ready(self):
        populate(self.repo)
        model_download.start(self.settings)
        with mock.patch.object(model_download.threading, "Thread") as worker:
            state = model_download.progress(Settings(model="medium", transcriber="faster-whisper"))
        worker.assert_not_called()
        self.assertEqual(state["model"], "medium")
        self.assertEqual(state["state"], model_download.UNAVAILABLE)
        self.assertEqual(state["reason"], "configuration-changed")

    def test_download_must_validate_its_result(self):
        with mock.patch.dict("sys.modules", {"huggingface_hub": mock.Mock(snapshot_download=mock.Mock(return_value=self.tmp.name))}):
            model_download._download(self.repo)
        self.assertEqual(model_download.snapshot()["state"], model_download.ERROR)

    def test_missing_dependency_leaves_a_retryable_error(self):
        with mock.patch.dict("sys.modules", {"huggingface_hub": None}):
            model_download._download(self.repo)
        self.assertEqual(model_download.snapshot()["state"], model_download.ERROR)

    def test_failure_then_native_retry_succeeds(self):
        downloads = mock.Mock(side_effect=[OSError("offline"), None])
        def download(repo, **kwargs):
            downloads(repo, **kwargs)
            populate(repo)
        with mock.patch.dict("sys.modules", {"huggingface_hub": mock.Mock(snapshot_download=download)}):
            model_download.start(self.settings)
            model_download._thread.join(2)
            self.assertEqual(model_download.snapshot()["state"], model_download.ERROR)
            model_download.start(self.settings)
            model_download._thread.join(2)
            self.assertTrue(model_download.ensure_ready(self.settings))
        self.assertEqual(downloads.call_count, 2)
        self.assertEqual(downloads.call_args.kwargs["cache_dir"], self.tmp.name)
        self.assertIn("model.bin", downloads.call_args.kwargs["allow_patterns"])

    def test_simultaneous_gestures_only_launch_one_download(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def download(repo, **kwargs):
            calls.append(repo)
            entered.set()
            release.wait(2)
            populate(repo)
        with mock.patch.dict("sys.modules", {"huggingface_hub": mock.Mock(snapshot_download=download)}):
            callers = [threading.Thread(target=model_download.start, args=(self.settings,)) for _ in range(12)]
            try:
                for caller in callers:
                    caller.start()
                self.assertTrue(entered.wait(2))
                for caller in callers:
                    caller.join(2)
                    self.assertFalse(caller.is_alive())
                self.assertFalse(model_download.ensure_ready(self.settings))
                self.assertEqual(calls, [self.repo])
            finally:
                release.set()
                model_download._thread.join(2)
        self.assertTrue(model_download.model_cached(self.settings))

    def test_interrupted_cache_remains_unready_after_offline_restart(self):
        populate(self.repo, complete=False)
        model_download.reset_for_tests()
        hub = mock.Mock(snapshot_download=mock.Mock(side_effect=OSError("offline")))
        with mock.patch.dict("sys.modules", {"huggingface_hub": hub}):
            model_download.start(self.settings)
            model_download._thread.join(2)
        self.assertEqual(model_download.progress()["state"], model_download.ERROR)
        self.assertFalse(diagnostics._whisper_model_cached(self.settings))

    def test_changing_model_while_worker_runs_does_not_overlap_downloads(self):
        entered = threading.Event()
        release = threading.Event()
        def download(repo, **kwargs):
            entered.set()
            release.wait(2)
            populate(repo)
        next_settings = Settings(model="medium", transcriber="faster-whisper")
        hub = mock.Mock(snapshot_download=mock.Mock(side_effect=download))
        with mock.patch.dict("sys.modules", {"huggingface_hub": hub}):
            try:
                model_download.start(self.settings)
                self.assertTrue(entered.wait(2))
                self.assertFalse(model_download.ensure_ready(next_settings))
                self.assertEqual(model_download.progress(next_settings)["model"], "medium")
                self.assertNotEqual(model_download.progress(next_settings)["state"], model_download.READY)
                hub.snapshot_download.assert_called_once()
            finally:
                release.set()
                model_download._thread.join(2)
            # Completion of the previous download cannot announce the new model
            # ready; the next native gesture explicitly starts its preparation.
            self.assertNotEqual(model_download.progress(next_settings)["state"], model_download.READY)
            model_download.start(next_settings)
            model_download._thread.join(2)
            self.assertEqual(hub.snapshot_download.call_count, 2)
            self.assertTrue(model_download.ensure_ready(next_settings))

    def test_thread_start_failure_does_not_leave_downloading_forever(self):
        with mock.patch.object(model_download.threading, "Thread") as worker:
            worker.return_value.start.side_effect = RuntimeError("no thread")
            model_download.start(self.settings)
        self.assertEqual(model_download.progress()["state"], model_download.ERROR)

    def test_progress_counts_partial_and_finished_blobs_without_percentage(self):
        folder = model_download.repo_dir(self.repo) / "blobs"
        folder.mkdir(parents=True)
        (folder / "a.incomplete").write_bytes(b"x" * 12)
        (folder / "b").write_bytes(b"x" * 18)
        model_download._set(state=model_download.DOWNLOADING, repo=self.repo, total_bytes=None)
        self.assertEqual(model_download.progress()["downloaded_bytes"], 30)
        self.assertIsNone(model_download.progress()["total_bytes"])


class InterfaceTest(unittest.TestCase):
    """The band that shows the download. Written against the files rather than a
    browser: what matters here is that nothing is said in one language only, and
    that the promises the design makes are actually in the stylesheet."""

    ASSETS = Path(__file__).resolve().parent.parent / "src" / "aparte" / "assets"

    def _read(self, name):
        return (self.ASSETS / name).read_text(encoding="utf-8")

    def test_every_string_exists_in_both_languages(self):
        # A key written once would be announced in English to a French screen
        # reader — and this band is the first thing a new install shows.
        i18n = self._read("i18n.js")
        for key in (
            "model.downloading",
            "model.ready",
            "model.failed",
            "model.progress",
            "model.progress_unknown",
            "model.once",
        ):
            self.assertEqual(i18n.count(f'"{key}"'), 2, key)

    def test_the_page_watches_the_read_only_route(self):
        self.assertIn("/api/model-state", self._read("app.js"))

    def test_only_the_phase_sentence_is_a_live_region(self):
        # The byte count changes every second: inside the live region it would
        # repeat itself endlessly in a screen reader's ear.
        html = self._read("index.html")
        notice = html[html.index('id="model-notice"') : html.index("</section>", html.index('id="model-notice"'))]
        self.assertEqual(notice.count("aria-live"), 1)
        self.assertIn('id="model-line" aria-live="polite"', notice)

    def test_the_sliding_bar_has_its_reduced_motion_counterpart(self):
        # A 30% fragment that no longer slides reads as "30% downloaded" and
        # lies; the byte count below keeps the state readable without it.
        css = self._read("app.css")
        reduced = css[css.index("@media (prefers-reduced-motion: reduce)") :]
        self.assertIn(".notice-meter.unknown", reduced)

    def test_the_band_takes_no_colour_flat(self):
        # The spotlight rule: only the recording disc may be a saturated flat.
        css = self._read("app.css")
        band = css[css.index(".notice {") : css.index("@keyframes notice-slide")]
        self.assertNotIn("--brand-fill", band)
        self.assertIn("var(--surface-2)", band)
