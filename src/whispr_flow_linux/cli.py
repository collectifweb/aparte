from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio import record_wav
from .clipboard import copy_text, paste_text
from .config import Settings, load_config, write_default_config
from .desktop import run_desktop
from .linux_desktop import (
    build_autostart_entry,
    build_desktop_entry,
    install_autostart_entry,
    install_desktop_entry,
    uninstall_autostart_entry,
)
from .notify import _preview, notify
from .polish import PolishOptions, build_polisher
from .session import get_active_session, start_toggle_recording, stop_toggle_recording
from .transcription import build_transcriber


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()

    try:
        if args.command == "polish":
            text = args.text if args.text is not None else sys.stdin.read()
            output = polish_text(text, args, settings)
            print(output)
            return 0
        if args.command == "transcribe":
            output = transcribe_path(Path(args.audio), args, settings)
            handle_output(output, args)
            return 0
        if args.command == "record":
            path = record_wav(args.seconds, args.sample_rate, settings.recorder)
            output = transcribe_path(path, args, settings)
            handle_output(output, args)
            return 0
        if args.command == "dictate":
            output = dictate_once(args, settings)
            print(output)
            return 0
        if args.command == "toggle":
            output = toggle_dictation(args, settings)
            print(output)
            return 0
        if args.command == "desktop":
            run_desktop(args.host, args.port, settings, open_browser=not args.no_browser)
            return 0
        if args.command == "doctor":
            print_doctor(settings)
            return 0
        if args.command == "config":
            handle_config_command(args)
            return 0
        if args.command == "install-desktop":
            handle_install_desktop(args)
            return 0
        if args.command == "install-autostart":
            handle_install_autostart(args)
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whispr-flow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    polish = subparsers.add_parser("polish", help="Polish dictated text from an argument or stdin.")
    polish.add_argument("text", nargs="?", help="Text to polish. Reads stdin when omitted.")
    add_polish_args(polish)

    transcribe = subparsers.add_parser("transcribe", help="Transcribe an audio file.")
    transcribe.add_argument("audio", help="Path to an audio file.")
    transcribe.add_argument("--polish", action="store_true", help="Polish the transcript before output.")
    add_common_output_args(transcribe)
    add_polish_args(transcribe)

    record = subparsers.add_parser("record", help="Record microphone audio, then transcribe it.")
    record.add_argument("--seconds", type=float, default=10.0, help="Recording duration.")
    record.add_argument("--sample-rate", type=int, default=16000, help="Recording sample rate.")
    record.add_argument("--polish", action="store_true", help="Polish the transcript before output.")
    add_common_output_args(record)
    add_polish_args(record)

    dictate = subparsers.add_parser(
        "dictate",
        help="Record, transcribe, polish, then paste/copy/print in one command.",
    )
    dictate.add_argument("--seconds", type=float, default=8.0, help="Recording duration.")
    dictate.add_argument("--sample-rate", type=int, default=16000, help="Recording sample rate.")
    dictate.add_argument(
        "--target",
        choices=["paste", "copy", "stdout"],
        default="paste",
        help="Where the final polished dictation should go.",
    )
    dictate.add_argument("--no-polish", action="store_true", help="Return raw transcription.")
    dictate.add_argument("--keep-audio", action="store_true", help="Keep the temporary recording file.")
    add_polish_args(dictate)

    toggle = subparsers.add_parser(
        "toggle",
        help="Toggle background recording for global hotkeys; second run transcribes and inserts.",
    )
    toggle.add_argument("--sample-rate", type=int, default=16000, help="Recording sample rate.")
    toggle.add_argument(
        "--target",
        choices=["paste", "copy", "stdout"],
        default="paste",
        help="Where the final polished dictation should go after stop.",
    )
    toggle.add_argument("--no-polish", action="store_true", help="Return raw transcription after stop.")
    toggle.add_argument("--keep-audio", action="store_true", help="Keep the temporary recording file.")
    toggle.add_argument("--status", action="store_true", help="Print whether a toggle recording is active.")
    add_polish_args(toggle)

    desktop = subparsers.add_parser("desktop", help="Launch the local Linux desktop app.")
    desktop.add_argument("--host", default="127.0.0.1")
    desktop.add_argument("--port", type=int, default=8765)
    desktop.add_argument(
        "--no-browser",
        action="store_true",
        help="Run the server without opening a browser (useful for autostart).",
    )

    subparsers.add_parser("doctor", help="Check optional Linux integrations and local backends.")

    config = subparsers.add_parser("config", help="Manage persistent Whispr Flow Linux configuration.")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_init = config_subparsers.add_parser("init", help="Write a default config file.")
    config_init.add_argument("--force", action="store_true", help="Overwrite an existing config file.")
    config_subparsers.add_parser("path", help="Print the active config path.")
    config_subparsers.add_parser("show", help="Print the merged active config.")

    install_desktop = subparsers.add_parser(
        "install-desktop",
        help="Install a user .desktop launcher for the local desktop app.",
    )
    install_desktop.add_argument("--force", action="store_true", help="Overwrite an existing desktop entry.")
    install_desktop.add_argument("--print", action="store_true", help="Print the generated desktop entry instead.")

    install_autostart = subparsers.add_parser(
        "install-autostart",
        help="Run the desktop server at login (writes a ~/.config/autostart entry).",
    )
    install_autostart.add_argument("--force", action="store_true", help="Overwrite an existing autostart entry.")
    install_autostart.add_argument("--print", action="store_true", help="Print the generated autostart entry instead.")
    install_autostart.add_argument("--remove", action="store_true", help="Remove the autostart entry.")

    return parser


def add_common_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--copy", action="store_true", help="Copy output to clipboard.")
    parser.add_argument("--paste", action="store_true", help="Type output into the active window.")


def add_polish_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--style", choices=["neutral", "formal", "casual", "very-casual"])
    parser.add_argument("--cleanup-level", choices=["light", "medium", "high"])


def polish_text(text: str, args: argparse.Namespace, settings: Settings) -> str:
    polisher = build_polisher(settings.polish_backend, settings.ollama_url, settings.ollama_model)
    return polisher.polish(
        text,
        PolishOptions(
            style=getattr(args, "style", None) or settings.default_style,
            language=settings.language,
            cleanup_level=getattr(args, "cleanup_level", None) or settings.cleanup_level,
            replacements=settings.replacements or {},
            snippets=settings.snippets or {},
        ),
    )


def transcribe_path(path: Path, args: argparse.Namespace, settings: Settings) -> str:
    backend = "text" if path.suffix.lower() in {".txt", ".md"} else settings.transcriber
    transcriber = build_transcriber(
        backend=backend,
        model=settings.model,
        language=settings.language,
        whisper_cpp=settings.whisper_cpp,
        device=settings.device,
        compute_type=settings.compute_type,
    )
    transcript = transcriber.transcribe(path).text
    if getattr(args, "polish", False):
        return polish_text(transcript, args, settings)
    return transcript


def dictate_once(args: argparse.Namespace, settings: Settings) -> str:
    notify("🎙️ Dictée", f"Enregistrement pendant {args.seconds:g}s…")
    path = record_wav(args.seconds, args.sample_rate, settings.recorder)
    notify("⏳ Transcription…", "Whispr Flow traite ta dictée.", urgency="low")
    try:
        transcribe_args = argparse.Namespace(
            polish=not args.no_polish,
            style=args.style or settings.default_style,
            cleanup_level=args.cleanup_level or settings.cleanup_level,
        )
        output = transcribe_path(path, transcribe_args, settings)
        _notify_inserted(output, args.target)
        if args.target == "paste":
            paste_text(output)
        elif args.target == "copy":
            copy_text(output)
        return output
    finally:
        if not args.keep_audio:
            path.unlink(missing_ok=True)


def _notify_inserted(output: str, target: str) -> None:
    if not output.strip():
        notify("🤫 Rien à transcrire", "Aucune parole détectée.", urgency="low")
        return
    if target == "copy":
        title = "📋 Copié dans le presse-papier"
    elif target == "stdout":
        title = "✅ Dictée prête"
    else:
        title = "✍️ Inséré"
    notify(title, _preview(output))


def toggle_dictation(args: argparse.Namespace, settings: Settings) -> str:
    active = get_active_session()
    if args.status:
        if active:
            return f"recording {active.audio_path}"
        return "idle"
    if not active:
        session = start_toggle_recording(args.sample_rate)
        notify("🎙️ Dictée en cours", "Réappuie sur le raccourci pour arrêter et insérer.")
        return f"Recording started: {session.audio_path}"

    session = stop_toggle_recording()
    notify("⏳ Transcription…", "Whispr Flow traite ta dictée.", urgency="low")
    try:
        transcribe_args = argparse.Namespace(
            polish=not args.no_polish,
            style=args.style or settings.default_style,
            cleanup_level=args.cleanup_level or settings.cleanup_level,
        )
        output = transcribe_path(session.audio_path, transcribe_args, settings)
        _notify_inserted(output, args.target)
        if args.target == "paste":
            paste_text(output)
        elif args.target == "copy":
            copy_text(output)
        return output
    finally:
        if not args.keep_audio:
            session.audio_path.unlink(missing_ok=True)


def handle_output(output: str, args: argparse.Namespace) -> None:
    if getattr(args, "paste", False):
        paste_text(output)
    elif getattr(args, "copy", False):
        copy_text(output)
    print(output)


def print_doctor(settings: Settings) -> None:
    import importlib.util
    import os
    import shutil

    has_faster_whisper = importlib.util.find_spec("faster_whisper") is not None
    has_openai_whisper = importlib.util.find_spec("whisper") is not None
    has_whisper_cpp = bool(settings.whisper_cpp or shutil.which("whisper-cli") or shutil.which("main"))
    has_arecord = shutil.which("arecord") is not None
    has_sounddevice = importlib.util.find_spec("sounddevice") is not None
    has_wayland_paste = shutil.which("wtype") is not None and bool(os.getenv("WAYLAND_DISPLAY"))
    has_x11_paste = shutil.which("xdotool") is not None and bool(os.getenv("DISPLAY"))
    has_wayland_copy = shutil.which("wl-copy") is not None and bool(os.getenv("WAYLAND_DISPLAY"))
    has_x11_copy = shutil.which("xclip") is not None or shutil.which("xsel") is not None
    active_toggle = get_active_session()

    checks = [
        ("config file", bool(settings.config_path and settings.config_path.exists())),
        ("toggle runtime writable", True),
        ("Python package faster_whisper", has_faster_whisper),
        ("Python package whisper", has_openai_whisper),
        ("Python package sounddevice", has_sounddevice),
        ("Python package soundfile", importlib.util.find_spec("soundfile") is not None),
        ("arecord", has_arecord),
        ("pw-record", shutil.which("pw-record") is not None),
        ("parec", shutil.which("parec") is not None),
        ("ffmpeg", shutil.which("ffmpeg") is not None),
        ("whisper.cpp executable", has_whisper_cpp),
        ("Wayland session", bool(os.getenv("WAYLAND_DISPLAY"))),
        ("X11 session", bool(os.getenv("DISPLAY"))),
        ("wl-copy", shutil.which("wl-copy") is not None),
        ("wtype", shutil.which("wtype") is not None),
        ("xclip", shutil.which("xclip") is not None),
        ("xdotool", shutil.which("xdotool") is not None),
    ]
    for label, ok in checks:
        marker = "ok" if ok else "missing"
        print(f"{marker:7} {label}")
    if active_toggle:
        print(f"status  toggle recording active: {active_toggle.audio_path}")
    else:
        print("status  toggle recording idle")

    recommendations: list[str] = []
    if not (has_faster_whisper or has_openai_whisper or has_whisper_cpp):
        recommendations.append('Install a local transcription backend: python -m pip install -e ".[whisper]"')
    if not (has_sounddevice or has_arecord):
        recommendations.append("Install a recorder: python sounddevice package or sudo apt install alsa-utils")
    if not (has_wayland_paste or has_x11_paste):
        recommendations.append("Install a paste tool: wtype on Wayland or xdotool on X11")
    if not (has_wayland_copy or has_x11_copy):
        recommendations.append("Install a clipboard tool: wl-clipboard on Wayland or xclip/xsel on X11")
    if settings.polish_backend == "ollama" and not _ollama_available(settings):
        recommendations.append("Start Ollama or switch to WHISPR_POLISH_BACKEND=heuristic")

    if recommendations:
        print("\nNext steps:")
        for item in recommendations:
            print(f"- {item}")


def _ollama_available(settings: Settings) -> bool:
    try:
        import requests

        response = requests.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except Exception:
        return False


def handle_config_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    if args.config_command == "init":
        path = write_default_config(settings.config_path, force=args.force)
        print(path)
        return
    if args.config_command == "path":
        print(settings.config_path)
        return
    if args.config_command == "show":
        import json

        print(json.dumps(load_config(settings.config_path), indent=2, ensure_ascii=False))
        return
    raise ValueError(f"Unknown config command: {args.config_command}")


def handle_install_desktop(args: argparse.Namespace) -> None:
    if args.print:
        print(build_desktop_entry(), end="")
        return
    path = install_desktop_entry(force=args.force)
    print(path)


def handle_install_autostart(args: argparse.Namespace) -> None:
    if args.remove:
        removed = uninstall_autostart_entry()
        print(f"removed {removed}" if removed else "no autostart entry to remove")
        return
    if args.print:
        print(build_autostart_entry(), end="")
        return
    path = install_autostart_entry(force=args.force)
    print(path)
