from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import history
from .audio import play_beep, record_wav
from .clipboard import copy_text, paste_text
from .config import Settings, load_config, write_default_config
from .desktop import run_desktop, transcribe_via_running_app
from .hotkey import (
    DEFAULT_KEY,
    DEFAULT_NAME,
    HotkeyUnsupported,
    install_hotkey,
    remove_hotkey,
)
from .platform_dispatch import desktop_integration
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
            handle_output(output, args, settings)
            return 0
        if args.command == "record":
            path = record_wav(args.seconds, args.sample_rate, settings.recorder, settings.microphone)
            output = transcribe_path(path, args, settings)
            handle_output(output, args, settings)
            return 0
        if args.command == "dictate":
            output = dictate_once(args, settings)
            print(output)
            return 0
        if args.command == "toggle":
            output = toggle_dictation(args, settings)
            print(output)
            return 0
        if args.command == "last":
            text = history.last(settings.history_persist)
            if not text:
                print("error: nothing dictated yet in this session", file=sys.stderr)
                return 1
            if args.target == "paste":
                paste_text(text, settings.paste_mode)
            elif args.target == "copy":
                copy_text(text)
            print(text)
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
        if args.command == "install-hotkey":
            handle_install_hotkey(args)
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aparte")
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

    last = subparsers.add_parser(
        "last",
        help="Re-insert the most recent dictation, without dictating again.",
    )
    last.add_argument(
        "--target",
        choices=["paste", "copy", "stdout"],
        default="stdout",
        help="Where the recalled dictation should go.",
    )

    desktop = subparsers.add_parser("desktop", help="Launch the local Linux desktop app.")
    desktop.add_argument("--host", default="127.0.0.1")
    desktop.add_argument("--port", type=int, default=8765)
    desktop.add_argument(
        "--no-browser",
        action="store_true",
        help="Run the server without opening a browser (useful for autostart).",
    )

    subparsers.add_parser("doctor", help="Check optional Linux integrations and local backends.")

    config = subparsers.add_parser("config", help="Manage persistent Aparté configuration.")
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

    install_hotkey = subparsers.add_parser(
        "install-hotkey",
        help="Bind a global keyboard shortcut to toggle dictation (Cinnamon/GNOME).",
    )
    install_hotkey.add_argument(
        "--key",
        default=None,
        help=(
            f"Shortcut accelerator (default: {DEFAULT_KEY}, or the existing binding if already set). "
            "Examples: '<Super>space', '<Control><Alt>d'."
        ),
    )
    install_hotkey.add_argument(
        "--target",
        choices=["paste", "copy", "stdout"],
        default="paste",
        help="Where dictation goes when the shortcut stops recording.",
    )
    install_hotkey.add_argument("--name", default=DEFAULT_NAME, help="Display name for the shortcut.")
    install_hotkey.add_argument("--print", action="store_true", help="Show what would be bound without applying it.")
    install_hotkey.add_argument("--remove", action="store_true", help="Remove the Aparté shortcut.")

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
            nonbreaking_spaces=settings.nonbreaking_spaces,
            trailing_space=settings.trailing_space,
            numbers_from=settings.numbers_from,
            short_text_words=settings.short_text_words,
        ),
    )


def transcribe_path(path: Path, args: argparse.Namespace, settings: Settings) -> str:
    backend = "text" if path.suffix.lower() in {".txt", ".md"} else settings.transcriber
    # L'application de bureau garde le modèle en mémoire ; ce processus-ci le
    # rechargerait. Quand elle répond, on lui passe l'audio — sinon rien ne
    # change et on charge le nôtre, exactement comme avant.
    transcript = None if backend == "text" else transcribe_via_running_app(path, settings.model)
    if transcript is None:
        transcriber = build_transcriber(
            backend=backend,
            model=settings.model,
            language=settings.language,
            whisper_cpp=settings.whisper_cpp,
            device=settings.device,
            compute_type=settings.compute_type,
            hotwords=settings.hotwords,
        )
        transcript = transcriber.transcribe(path).text
    if getattr(args, "polish", False):
        return polish_text(transcript, args, settings)
    return transcript


def dictate_once(args: argparse.Namespace, settings: Settings) -> str:
    notify("🎙️ Dictée", f"Enregistrement pendant {args.seconds:g}s…")
    if settings.beep:
        play_beep("start")
    path = record_wav(args.seconds, args.sample_rate, settings.recorder, settings.microphone)
    if settings.beep:
        play_beep("stop")
    notify("⏳ Transcription…", "Aparté traite ta dictée.", urgency="low")
    try:
        transcribe_args = argparse.Namespace(
            polish=not args.no_polish,
            style=args.style or settings.default_style,
            cleanup_level=args.cleanup_level or settings.cleanup_level,
        )
        output = transcribe_path(path, transcribe_args, settings)
        if not output.strip():
            # Ni copie ni collage : `paste_text` passe d'abord par le
            # presse-papiers, et une dictée vide y écraserait ce que
            # l'utilisateur gardait.
            _notify_nothing_heard()
            return output
        # L'historique avant l'insertion : si le collage casse, le texte reste
        # rattrapable par `aparte last`.
        history.record(output, settings.history_persist)
        _deliver(output, args.target, settings)
        return output
    finally:
        if not args.keep_audio:
            path.unlink(missing_ok=True)


def _deliver(output: str, target: str, settings: Settings) -> None:
    """Placer la dictée, puis seulement la signaler.

    L'ordre compte. Notifier avant d'insérer annonce un succès que l'échec
    suivant ne peut plus démentir : l'erreur part sur `stderr`, et un raccourci
    clavier n'a personne pour la lire.
    """
    try:
        if target == "paste":
            paste_text(output, settings.paste_mode)
        elif target == "copy":
            copy_text(output)
    except Exception as exc:
        notify(
            "⚠️ Dictée non insérée",
            f"{exc} Aparté a tenté de la garder dans l'historique ; essaie « aparte last ».",
            urgency="critical",
        )
        raise
    _notify_inserted(output, target)


def _notify_nothing_heard() -> None:
    notify("🤫 Rien à transcrire", "Aucune parole détectée.", urgency="low")


def _notify_inserted(output: str, target: str) -> None:
    if target == "copy":
        title = "📋 Copié dans le presse-papier"
    elif target == "stdout":
        title = "✅ Dictée prête"
    else:
        title = "✍️ Inséré (aussi dans le presse-papier)"
    notify(title, _preview(output))


def toggle_dictation(args: argparse.Namespace, settings: Settings) -> str:
    active = get_active_session()
    if args.status:
        if active:
            return f"recording {active.audio_path}"
        return "idle"
    if not active:
        if settings.beep:
            play_beep("start")
        session = start_toggle_recording(
            args.sample_rate, settings.microphone, settings.max_recording_seconds
        )
        notify("🎙️ Dictée en cours", "Réappuie sur le raccourci pour arrêter et insérer.")
        return f"Recording started: {session.audio_path}"

    session = stop_toggle_recording()
    if settings.beep:
        play_beep("stop")
    notify("⏳ Transcription…", "Aparté traite ta dictée.", urgency="low")
    try:
        transcribe_args = argparse.Namespace(
            polish=not args.no_polish,
            style=args.style or settings.default_style,
            cleanup_level=args.cleanup_level or settings.cleanup_level,
        )
        output = transcribe_path(session.audio_path, transcribe_args, settings)
        if not output.strip():
            _notify_nothing_heard()
            return output
        history.record(output, settings.history_persist)
        _deliver(output, args.target, settings)
        return output
    finally:
        if not args.keep_audio:
            session.audio_path.unlink(missing_ok=True)


def handle_output(output: str, args: argparse.Namespace, settings: Settings) -> None:
    if getattr(args, "paste", False):
        paste_text(output, settings.paste_mode)
    elif getattr(args, "copy", False):
        copy_text(output)
    print(output)


def print_doctor(settings: Settings) -> None:
    from .diagnostics import collect_diagnostics

    diagnostics = collect_diagnostics(settings)
    category = None
    for check in diagnostics["checks"]:
        if check["category"] != category:
            category = check["category"]
            print(f"\n{category}")
        marker = "ok" if check["ok"] else "missing"
        print(f"  {marker:7} {check['label']}")

    summary = diagnostics["summary"]
    print(f"\nstatus  {'recording active' if diagnostics['recording_active'] else 'idle'}")
    print(f"ready   {'yes' if summary['ready'] else 'no — see fixes below'}")

    hotkey = diagnostics["hotkey"]
    if hotkey["bound_key"]:
        print(f"hotkey  bound to {hotkey['bound_key_label']}")
    elif hotkey["supported"]:
        print("hotkey  not bound — run: aparte install-hotkey")
    else:
        print(f"hotkey  bind manually: {hotkey['command']}")

    fixes = [c for c in diagnostics["checks"] if not c["ok"] and c["fix"]]
    if fixes:
        print("\nNext steps:")
        for check in fixes:
            flag = " (required)" if check["essential"] else ""
            print(f"- {check['label']}{flag}: {check['fix']}")


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
    desktop = desktop_integration()
    if args.print:
        print(desktop.build_desktop_entry(), end="")
        return
    path = desktop.install_desktop_entry(force=args.force)
    print(path)


def handle_install_autostart(args: argparse.Namespace) -> None:
    desktop = desktop_integration()
    if args.remove:
        removed = desktop.uninstall_autostart_entry()
        print(f"removed {removed}" if removed else "no autostart entry to remove")
        return
    if args.print:
        print(desktop.build_autostart_entry(), end="")
        return
    path = desktop.install_autostart_entry(force=args.force)
    print(path)


def handle_install_hotkey(args: argparse.Namespace) -> None:
    from .hotkey import command_string, current_binding, detect_desktop, key_label, manual_instructions, aparte_command

    command = command_string(aparte_command("toggle", "--target", args.target))
    if args.remove:
        removed = remove_hotkey(args.name)
        print(f"removed {', '.join(removed)}" if removed else "no Aparté shortcut to remove")
        return
    if args.print:
        key = args.key or current_binding(args.name) or DEFAULT_KEY
        print(f"desktop  {detect_desktop() or 'unknown'}")
        print(f"shortcut {key_label(key)}")
        print(f"command  {command}")
        print(manual_instructions(command, key, detect_desktop()))
        return
    try:
        result = install_hotkey(args.key, args.target, args.name)
    except HotkeyUnsupported as exc:
        print(exc.instructions())
        return
    print(f"Bound {key_label(result.key)} → {result.command} ({result.desktop}, {result.slot}).")
    print("Press it once to start dictating, again to transcribe and insert.")
