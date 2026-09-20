#!/usr/bin/env python3
"""Run tests in a child process with private configuration, data and caches.

No APARTE_RUNTIME_DIR override: the suite exercises XDG_RUNTIME_DIR fallback.
The macOS selection excludes Linux-only integrations and runs Mac clipboard
classes explicitly; the full suite remains mandatory on Linux.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MACOS_TESTS = (
    "test_macos_desktop", "test_macos_install", "test_macos_permissions",
    "test_macos_insert", "test_macos_hotkey", "test_macos_recording",
    "test_macos_runloop", "test_macos_tray", "test_platform_dispatch",
    "test_packaging", "test_config", "test_config_persistence",
    "test_history", "test_history_macos_retention", "test_recovery",
    "test_transcription", "test_hallucinations", "test_polish", "test_numbers",
    "test_model_download", "test_clipboard.CopyMacTest", "test_clipboard.PasteMacTest",
    "test_ci_isolation", "test_macos_ui", "test_macos_reliability",
    "test_macos_model_gate", "test_recording_ui", "test_recovery_ui",
)


def isolated_environment(root: Path, inherited: dict[str, str]) -> dict[str, str]:
    """Build an environment before importing any application module."""
    environment = {
        key: value for key, value in inherited.items()
        if not key.startswith(("APARTE_", "MURMUR_"))
    }
    locations = {
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "XDG_STATE_HOME": root / "state",
        "XDG_RUNTIME_DIR": root / "runtime",
        "XDG_CACHE_HOME": root / "cache",
        "HF_HOME": root / "cache" / "huggingface",
        "HF_HUB_CACHE": root / "cache" / "huggingface" / "hub",
        "HUGGINGFACE_HUB_CACHE": root / "cache" / "huggingface" / "hub",
        "TORCH_HOME": root / "cache" / "torch",
        "TMPDIR": root / "tmp",
    }
    for name, path in locations.items():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        environment[name] = str(path)
    environment.update({
        "APARTE_CONFIG": str(root / "config" / "aparte" / "config.json"),
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests"))),
        "PYTHONNOUSERSITE": "1",
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    return environment


def test_command(suite: str, names: list[str]) -> list[str]:
    command = [sys.executable, "-m", "unittest"]
    if names:
        return [*command, "-v", *names]
    if suite == "macos":
        return [*command, "-v", *MACOS_TESTS]
    return [*command, "discover", "-s", "tests", "-t", "tests", "-v"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "macos"), default="all")
    parser.add_argument("tests", nargs="*", help="Optional unittest module/class names")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aparte-tests-") as directory:
        environment = isolated_environment(Path(directory), dict(os.environ))
        return subprocess.run(test_command(args.suite, args.tests), cwd=ROOT, env=environment).returncode


if __name__ == "__main__":
    raise SystemExit(main())
