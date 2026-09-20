from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from . import history, recovery
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
from .platform_dispatch import desktop_integration, is_macos
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
            _finish_capture(path, args, settings,
                            lambda output: handle_output(output, args, settings))
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
        if args.command == "install-app":
            handle_install_app(args)
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

    desktop = subparsers.add_parser("desktop", help="Launch the local desktop app.")
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

    install_app = subparsers.add_parser(
        "install-app",
        help="macOS: build Aparté.app in ~/Applications so permissions are granted to Aparté.",
    )
    install_app.add_argument("--open", action="store_true", help="Open the application once installed.")
    install_app.add_argument(
        "--force",
        action="store_true",
        help="Replace a bundle that differs. macOS then forgets the granted permissions.",
    )
    install_app.add_argument("--remove", action="store_true", help="Remove the application bundle.")

    install_autostart = subparsers.add_parser(
        "install-autostart",
        help="Run the desktop server at login (writes a ~/.config/autostart entry).",
    )
    install_autostart.add_argument("--force", action="store_true", help="Overwrite an existing autostart entry.")
    install_autostart.add_argument("--print", action="store_true", help="Print the generated autostart entry instead.")
    install_autostart.add_argument("--remove", action="store_true", help="Remove the autostart entry.")

    install_hotkey = subparsers.add_parser(
        "install-hotkey",
        help="Configure the dictation shortcut (macOS or Cinnamon/GNOME).",
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
    install_hotkey.add_argument(
        "--diagnostic",
        action="store_true",
        help="(macOS) Register the shortcut live and log each event, to check it works (M8).",
    )

    recover = subparsers.add_parser("recover", help="Recover a failed dictation (one hour).")
    commands = recover.add_subparsers(dest="recovery_command", required=True)
    commands.add_parser("list", help="List recoverable captures without their content.")
    retry = commands.add_parser("retry", help="Recover text without automatic insertion.")
    retry.add_argument("id")
    retry.add_argument("--target", choices=["stdout", "copy"], default="stdout")
    retry.add_argument("--no-polish", action="store_true")
    add_polish_args(retry)
    delete = commands.add_parser("delete", help="Delete a retained capture.")
    delete.add_argument("id")
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
    return _finish_dictation(path, args, settings)


def _finish_dictation(path: Path, args: argparse.Namespace, settings: Settings) -> str:
    transcribe_args = argparse.Namespace(
        polish=not args.no_polish,
        style=args.style or settings.default_style,
        cleanup_level=args.cleanup_level or settings.cleanup_level,
    )
    return _finish_capture(path, transcribe_args, settings,
                           lambda output: deliver_transcript(output, args.target, settings),
                           keep_audio=args.keep_audio)


def _finish_capture(path: Path, args: argparse.Namespace, settings: Settings,
                    deliver: Callable[[str], object], *, keep_audio: bool = False) -> str:
    """Release owned audio only after delivery or a successful recovery copy.

    Capture the raw transcript separately, before polishing can fail. Imported
    files passed to ``transcribe`` never enter this helper: they remain owned by
    the caller and must never be removed.
    """
    raw = None
    remove_audio = False
    try:
        raw_args = argparse.Namespace(**{**vars(args), "polish": False})
        raw = transcribe_path(path, raw_args, settings)
        output = polish_text(raw, args, settings) if getattr(args, "polish", False) and raw.strip() else raw
        deliver(output)
        remove_audio = True
        return output
    except Exception:
        try:
            identifier = recovery.save_failure(path, raw_text=raw)
        except Exception:
            detail = f"La récupération a échoué. L’audio original est conservé : {path}"
        else:
            remove_audio = True
            detail = ("Audio récupérable pendant une heure. Ouvre Aparté pour réessayer "
                      f"ou utilise « aparte recover retry {identifier} ».")
        # A broken notification cannot hide the processing error or change the
        # cleanup decision. CLI users also need a visible recovery instruction.
        print(detail, file=sys.stderr)
        try:
            notify("⚠️ Dictée à récupérer", detail, urgency="critical")
        except Exception:
            pass
        raise
    finally:
        if remove_audio and not keep_audio:
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


def deliver_transcript(output: str, target: str, settings: Settings) -> bool:
    """Placer la dictée transcrite, dans l'ordre qui la rend rattrapable.

    Vide → on ne touche à rien : `paste_text` passe d'abord par le presse-papiers,
    et une dictée vide y écraserait ce que l'utilisateur gardait. Sinon l'historique
    s'écrit AVANT l'insertion : si le collage casse, le texte reste rattrapable par
    « aparte last ». Renvoie True si le texte a été livré, False s'il était vide.

    Un seul endroit pour cet ordre, partagé par `dictate_once`, `toggle_dictation`
    et le worker macOS in-process (`RecordingController`) : le dupliquer risquerait
    une dérive silencieuse sur le chemin que personne n'exerce à la main.
    """
    if not output.strip():
        _notify_nothing_heard()
        return False
    history.record(output, settings.history_persist)
    _deliver(output, target, settings)
    return True


def retry_recovery(identifier: str, args: argparse.Namespace, settings: Settings) -> str:
    """Keep the capture until explicit deletion/expiry, even after printing text."""
    with recovery.claim(identifier) as item:
        raw = item.raw_text
        if raw is None:
            raw = transcribe_path(item.audio_path, argparse.Namespace(polish=False), settings)
            recovery.update_raw(item, raw)
        output = raw if args.no_polish or not raw.strip() else polish_text(raw, args, settings)
        if output.strip():
            history.record(output, settings.history_persist)
            if args.target == "copy":
                copy_text(output)
        return output


def polish_for_delivery(transcript: str, settings: Settings) -> str:
    """Polir le texte dicté pour le chemin résident (raccourci macOS).

    Le raccourci n'a pas d'options par appel : il prend les défauts des réglages
    (polissage activé, style et niveau de nettoyage de la config). C'est le pendant
    du polissage que `transcribe_path` applique côté ligne de commande — sans ce
    passage, le raccourci macOS livrerait du texte brut, sans typographie française,
    sur le chemin principal du produit. Une chaîne vide reste vide, sans polir.
    """
    if not transcript.strip():
        return transcript
    polish_args = argparse.Namespace(
        polish=True,
        style=settings.default_style,
        cleanup_level=settings.cleanup_level,
    )
    return polish_text(transcript, polish_args, settings)


def toggle_dictation(args: argparse.Namespace, settings: Settings) -> str:
    active = get_active_session()
    if args.status:
        if active:
            return f"recording {active.audio_path}"
        return "idle"
    if is_macos():
        # The Linux toggle spawns detached arecord processes coordinated through a
        # session file — none of which exists on macOS, where recording lives in the
        # resident server's RecordingController, driven by the global shortcut (M5).
        # A fresh CLI process can't reach that in-memory state, so don't fake it.
        message = (
            "La bascule dictée sur macOS passe par le raccourci global ou "
            "l'application résidente ; « aparte dictate » fait une passe unique."
        )
        notify("🎙️ Bascule indisponible", message, urgency="low")
        return message
    if not active:
        if settings.beep:
            play_beep("start")
        try:
            session = start_toggle_recording(
                args.sample_rate, settings.microphone, settings.max_recording_seconds
            )
        except RecordingError as exc:
            # Un raccourci clavier n'a personne pour lire `stderr` — Cinnamon le
            # jette. Sans cette notification, un démarrage refusé est un appui qui
            # n'a rien fait : l'appui suivant, celui qui croit arrêter, ne trouve
            # plus de session et ouvre le micro pour un enregistrement entier.
            notify(
                "⚠️ Dictée non démarrée",
                f"{exc} Rien n'enregistre — réappuie pour réessayer.",
                urgency="critical",
            )
            raise
        notify("🎙️ Dictée en cours", "Réappuie sur le raccourci pour arrêter et insérer.")
        return f"Recording started: {session.audio_path}"

    session = stop_toggle_recording()
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
    # A macOS permission has no shell fix but carries its remedy in the detail;
    # surface those too so the CLI is not silent about what to do. On Linux this
    # list is empty — every Linux check ships a fix — so the output is unchanged.
    guidance = [c for c in diagnostics["checks"] if not c["ok"] and not c["fix"] and c["detail"]]
    if fixes or guidance:
        print("\nNext steps:")
        for check in fixes:
            flag = " (required)" if check["essential"] else ""
            print(f"- {check['label']}{flag}: {check['fix']}")
        for check in guidance:
            flag = " (required)" if check["essential"] else ""
            print(f"- {check['label']}{flag}: {check['detail']}")


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


def handle_install_app(args: argparse.Namespace) -> None:
    """`aparte install-app` — the second of the two commands a Mac install takes.

    macOS only: on Linux the launcher is a `.desktop` entry and `install-desktop`
    already does the job. Refusing here rather than half-working elsewhere.
    """
    from .macos_desktop import stable_interpreter
    from .macos_install import install_app, open_app, uninstall_app

    if not is_macos():
        raise RuntimeError(
            "install-app builds a macOS application bundle. On Linux, use `aparte install-desktop`."
        )
    if args.remove:
        print("removed" if uninstall_app() else "no application bundle to remove")
        return
    # The interpreter is named through Homebrew's version-stable `opt` path: the
    # `Cellar` one disappears at the first `brew upgrade`, and a launcher pointing
    # at a path that no longer exists is a bundle that no longer starts.
    result = install_app(stable_interpreter(sys.executable), force=args.force)
    print(f"{result['outcome']}: {result['bundle']}")
    if args.open:
        open_app()


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
    if is_macos():
        _install_hotkey_macos(args)
        return
    if getattr(args, "diagnostic", False):
        # Linux binds through gsettings; there is no live registration to observe.
        print("The --diagnostic mode is macOS-only.")
        return
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


def _install_hotkey_macos(args: argparse.Namespace) -> None:
    """macOS install-hotkey: persist the combo to config.json (no gsettings here).

    Unlike Linux, "installing" only records the choice — the resident server
    registers it at startup. So a reserved/taken combo surfaces at runtime
    (doctor, /api/hotkey-state), not here. Delivery is always paste on macOS.
    """
    from .config import load_config, update_config
    from .macos_hotkey import DEFAULT_HOTKEY, HotkeyError, hotkey_label, normalize_hotkey

    if args.diagnostic:
        _run_hotkey_diagnostic_macos(args)
        return

    if args.target != "paste":
        # The resident worker always delivers to paste (macos_recording); accepting
        # copy/stdout would silently promise a mode the shortcut cannot honor.
        print("On macOS the dictation shortcut always inserts (--target paste).")
        print("For copy or stdout, run the dictation directly: aparte dictate --target copy.")
        return

    if args.remove:
        update_config({"hotkey": ""})
        print("Removed the dictation shortcut. Restart Aparté for it to take effect.")
        return

    if args.print:
        combo = args.key or str(load_config().get("hotkey", "") or "") or DEFAULT_HOTKEY
        try:
            print(f"shortcut {hotkey_label(combo)}  ({normalize_hotkey(combo)})")
        except HotkeyError as exc:
            print(f"Invalid shortcut {combo!r}: {exc}")
            return
        print("Active only while Aparté is running (it registers the shortcut at startup).")
        print("Set or clear it: aparte install-hotkey --key '<combo>'  /  --remove.")
        print("Keep Aparté open for the shortcut; use its menu to configure it.")
        return

    combo = args.key or DEFAULT_HOTKEY
    try:
        canonical = normalize_hotkey(combo)
    except HotkeyError as exc:
        print(f"Invalid shortcut {combo!r}: {exc}")
        print("Use the macOS format, e.g. 'ctrl+opt+d' or 'cmd+shift+space'.")
        return
    update_config({"hotkey": canonical})
    print(f"Set the dictation shortcut to {hotkey_label(canonical)}  ({canonical}).")
    print("It takes effect when Aparté (re)starts, and works only while it runs.")


def _run_hotkey_diagnostic_macos(args: argparse.Namespace) -> None:
    """M8 native smoke: register the combo live and log each raw event.

    Reads --key, else the configured combo, else the default. This registers the
    real shortcut on its own AppKit loop, so it must not run while the resident
    server already holds it — quit Aparté first, or pass a different --key."""
    from .config import load_config
    from .macos_hotkey import DEFAULT_HOTKEY, HotkeyError, normalize_hotkey
    from .macos_runloop import run_hotkey_diagnostic

    combo = args.key or str(load_config().get("hotkey", "") or "") or DEFAULT_HOTKEY
    try:
        canonical = normalize_hotkey(combo)
    except HotkeyError as exc:
        print(f"Invalid shortcut {combo!r}: {exc}")
        print("Use the macOS format, e.g. 'ctrl+opt+d' or 'cmd+shift+space'.")
        return
    run_hotkey_diagnostic(canonical)
