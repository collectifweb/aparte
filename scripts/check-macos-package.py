#!/usr/bin/env python3
"""Smoke-test installed native dependencies without opening a device or app.

The accompanying macOS unit suite performs real clang/codesign checks in
NativeBundleSignatureTest. This check only imports the real optional modules and
checks packaged resources; it never builds a model, requests TCC, or starts AppKit.
"""
from __future__ import annotations

import importlib
from importlib import metadata, resources
import json
import platform
import sys


def main() -> int:
    if sys.platform != "darwin":
        print("Native package check requires macOS.", file=sys.stderr)
        return 2
    modules = (
        "AppKit", "Foundation", "Quartz", "AVFoundation", "ApplicationServices",
        "rumps", "faster_whisper", "ctranslate2", "sounddevice", "soundfile",
        "aparte.macos_hotkey", "aparte.macos_insert", "aparte.macos_runloop",
    )
    for module in modules:
        importlib.import_module(module)
    assets = resources.files("aparte").joinpath("assets")
    for name in ("index.html", "app.js", "app.css", "i18n.js", "aparte.icns"):
        if not assets.joinpath(name).is_file():
            raise RuntimeError(f"Missing packaged asset: {name}")
    print(json.dumps({
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "imports": list(modules),
        "packages": {name: metadata.version(name) for name in (
            "aparte", "faster-whisper", "ctranslate2", "sounddevice", "soundfile", "rumps",
            "pyobjc-core",
        )},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
