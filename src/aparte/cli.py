from __future__ import annotations

import argparse
from contextlib import ExitStack
import sys
from pathlib import Path

from . import history, recovery, technical_log
from .audio import RecordingError, play_beep, record_wav
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
from .linux_desktop import (
    build_autostart_entry,
    build_desktop_entry,
    install_autostart_entry,
    install_desktop_entry,
    uninstall_autostart_entry,
)
from .notify import _preview, notify
from .lifecycle import get_dictation_state, processing_dictation
from .polish import PolishOptions, build_polisher
from .session import (
    get_active_session, start_toggle_recording, stop_toggle_recording,
    toggle_session_transition, ToggleSessionError, RecordingStartError,
)
from .transcription import build_transcriber


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "toggle" and args.hotkey:
        if args.target == "stdout" or args.status:
            parser.error("--hotkey cannot be combined with --target stdout or --status")
        return _hotkey_main(args)
    settings = Settings.from_env()

    # Purge even when the desktop app is closed. A cleanup failure must not
    # prevent diagnostics or a new dictation from being used.
    if args.command in {"dictate", "toggle", "recover"}:
        try:
            recovery.sweep()
        except (OSError, RuntimeError):
            pass

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
        if args.command == "recover":
            recovery.sweep()
            if args.recovery_command == "list":
                import json

                print(json.dumps(recovery.entries(), ensure_ascii=False))
            elif args.recovery_command == "delete":
                recovery.discard(args.id)
            else:
                print(retry_recovery(args.id, args, settings))
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


def _hotkey_main(args: argparse.Namespace) -> int:
    # Suppress even native libraries and subprocesses; redirecting print alone
    # would still leak text from a backend or an insertion failure to a wrapper.
    try:
        technical_log.silence_process()
    except (OSError, ValueError) as exc:
        # Fail closed if the output cannot be silenced; do not start a capture.
        technical_log.write_event("failed", error_type=type(exc).__name__)
        return 1
    technical_log.write_event("invoked")
    try:
        settings = Settings.from_env()
        try:
            recovery.sweep()
        except (OSError, RuntimeError):
            pass
        toggle_dictation(args, settings)
    except Exception as exc:
        technical_log.write_event("failed", error_type=type(exc).__name__)
        return 1
    technical_log.write_event("completed")
    return 0


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
    toggle.add_argument("--hotkey", action="store_true", help="Private shortcut mode: technical diagnostics only, no console output.")
    add_polish_args(toggle)

    recover = subparsers.add_parser("recover", help="Récupérer une dictée en échec (une heure).")
    recovery_commands = recover.add_subparsers(dest="recovery_command", required=True)
    recovery_commands.add_parser("list", help="Lister les dictées récupérables, sans leur contenu.")
    retry = recovery_commands.add_parser("retry", help="Réessayer une dictée, sans collage automatique.")
    retry.add_argument("id")
    retry.add_argument("--target", choices=["copy", "stdout"], default="copy")
    retry.add_argument("--no-polish", action="store_true", help="Récupérer le texte brut.")
    add_polish_args(retry)
    delete = recovery_commands.add_parser("delete", help="Supprimer définitivement une capture.")
    delete.add_argument("id")

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
        try:
            return polish_text(transcript, args, settings)
        except Exception as exc:
            raise _PolishFailure(str(exc), transcript) from exc
    return transcript


def dictate_once(args: argparse.Namespace, settings: Settings) -> str:
    notify("🎙️ Dictée", f"Enregistrement pendant {args.seconds:g}s…")
    if settings.beep:
        play_beep("start")
    path = record_wav(args.seconds, args.sample_rate, settings.recorder, settings.microphone)
    if settings.beep:
        play_beep("stop")
    notify("⏳ Transcription…", "Aparté traite ta dictée.", urgency="low")
    with processing_dictation():
        return _finish_dictation(path, args, settings)


class _PolishFailure(RuntimeError):
    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


def _finish_dictation(path: Path, args: argparse.Namespace, settings: Settings) -> str:
    remove_audio = not args.keep_audio
    try:
        transcribe_args = argparse.Namespace(
            polish=not args.no_polish,
            style=args.style or settings.default_style,
            cleanup_level=args.cleanup_level or settings.cleanup_level,
        )
        try:
            output = transcribe_path(path, transcribe_args, settings)
        except Exception as exc:
            try:
                identifier = recovery.save_failure(path, raw_text=getattr(exc, "raw_text", None))
            except Exception:
                # A full disk must not turn the fallback into data loss.
                remove_audio = False
                notify(
                    "⚠️ Dictée non traitée",
                    f"La récupération a échoué. L’audio original est conservé : {path}",
                    urgency="critical",
                )
            else:
                notify(
                    "⚠️ Dictée à récupérer",
                    "Audio récupérable pendant une heure. Ouvre Aparté pour réessayer "
                    f"ou utilise « aparte recover retry {identifier} ».",
                    urgency="critical",
                )
            raise
        if not output.strip():
            _notify_nothing_heard()
            return output
        history.record(output, settings.history_persist)
        _deliver(output, args.target, settings)
        return output
    finally:
        if remove_audio:
            path.unlink(missing_ok=True)


def retry_recovery(identifier: str, args: argparse.Namespace, settings: Settings) -> str:
    """Retry once under a claim. Copy by default; never paste automatically."""
    if args.target not in {"copy", "stdout"}:
        raise ValueError("La récupération propose uniquement copier ou afficher le texte.")
    with processing_dictation(), recovery.claim(identifier) as item:
        try:
            raw = item.raw_text
            if raw is None:
                transcribe_args = argparse.Namespace(polish=False)
                raw = transcribe_path(item.audio_path, transcribe_args, settings)
                recovery.update_raw(item, raw)
            output = raw if args.no_polish or not raw.strip() else polish_text(raw, args, settings)
            if output.strip():
                history.record(output, settings.history_persist)
                _deliver(output, args.target, settings)
            else:
                _notify_nothing_heard()
            recovery.complete(item)
            return output
        except Exception:
            notify(
                "⚠️ Récupération interrompue",
                "La dictée reste disponible jusqu’à son expiration initiale. "
                "Tu peux aussi récupérer le texte brut s’il est disponible.",
                urgency="critical",
            )
            raise


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
    if args.status:
        try:
            return get_dictation_state()
        except (OSError, ToggleSessionError):
            return "unknown"
    with ExitStack() as processing:
        with toggle_session_transition():
            active = get_active_session()
            if not active:
                if settings.beep:
                    play_beep("start")
                try:
                    session = start_toggle_recording(
                        args.sample_rate, settings.microphone, settings.max_recording_seconds
                    )
                except RecordingError as exc:
                    if getattr(args, "hotkey", False) and isinstance(exc, RecordingStartError):
                        technical_log.write_event("audio_start_failed", audio_diagnostic=str(exc))
                    # Un raccourci clavier n'a personne pour lire `stderr` — Cinnamon le
                    # jette. Sans cette notification, un démarrage refusé est un appui qui
                    # n'a rien fait : l'appui suivant, celui qui croit arrêter, ne trouve
                    # plus de session et ouvre le micro pour un enregistrement entier.
                    notify(
                        "⚠️ Dictée non démarrée",
                        f"{getattr(exc, 'user_message', str(exc))} Rien n'enregistre — réappuie pour réessayer.",
                        urgency="critical",
                    )
                    raise
                notify("🎙️ Dictée en cours", "Réappuie sur le raccourci pour arrêter et insérer.")
                return f"Recording started: {session.audio_path}"

            try:
                # Publish while the capture transition is still held: Quit must see
                # either the recorder or its processing, never a gap between them.
                processing.enter_context(processing_dictation())
                session = stop_toggle_recording()
            except ToggleSessionError as exc:
                notify("⚠️ Arrêt de dictée non confirmé", str(exc), urgency="critical")
                raise
        if settings.beep:
            play_beep("stop")
        notify("⏳ Transcription…", "Aparté traite ta dictée.", urgency="low")
        return _finish_dictation(session.audio_path, args, settings)


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
    print(f"\nstatus  {diagnostics['dictation_state']}")
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


def handle_install_hotkey(args: argparse.Namespace) -> None:
    from .hotkey import current_binding, detect_desktop, key_label, manual_instructions, toggle_command

    command = toggle_command(args.target)
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
