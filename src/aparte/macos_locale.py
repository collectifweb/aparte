"""Native UI language, independent from the chosen dictation language."""
from __future__ import annotations

import os
import sys


def language() -> str:
    # Finder/launchd do not normally export LANG. Foundation is authoritative on
    # macOS; environment variables remain the portable fallback for CLI/tests.
    if sys.platform == "darwin":
        try:
            from Foundation import NSLocale
            preferred = NSLocale.preferredLanguages()
            if preferred:
                return "fr" if str(preferred[0]).lower().startswith("fr") else "en"
        except Exception:
            pass
    value = os.getenv("LC_ALL") or os.getenv("LC_MESSAGES") or os.getenv("LANG") or ""
    return "fr" if value.lower().startswith("fr") else "en"


_MESSAGES = {
    "fr": {
        "busy_title": "🎙️ Déjà en cours", "busy": "Une dictée est déjà en traitement.",
        "error_title": "⚠️ Dictée interrompue",
        "saved": "La capture est récupérable pendant une heure dans Aparté.",
        "unsaved": "Impossible de sauvegarder la capture. Libère de l’espace puis réessaie avant de quitter.",
        "retry": "Réessaie après avoir corrigé le problème.",
        "audio_warning": "⚠️ Capture incomplète",
        "overflow": "Le micro a perdu des échantillons. Vérifie le texte dicté.",
        "cap": "La durée maximale a été atteinte. Vérifie le texte puis poursuis avec une nouvelle dictée.",
        "model_wait": "Le modèle n’est pas prêt. Consulte Aparté puis réappuie pour réessayer.",
    },
    "en": {
        "busy_title": "🎙️ Already busy", "busy": "A dictation is already being processed.",
        "error_title": "⚠️ Dictation interrupted",
        "saved": "The recording can be recovered in Aparté for one hour.",
        "unsaved": "The recording could not be saved. Free disk space and try again before quitting.",
        "retry": "Fix the problem and try again.",
        "audio_warning": "⚠️ Incomplete recording",
        "overflow": "The microphone lost audio samples. Review the dictated text.",
        "cap": "The recording limit was reached. Review the text, then start another dictation to continue.",
        "model_wait": "The model is not ready. Check Aparté, then press the shortcut again to retry.",
    },
}


def message(key: str) -> str:
    return _MESSAGES[language()][key]
