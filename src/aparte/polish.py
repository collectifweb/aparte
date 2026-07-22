from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from .numbers import convert as convert_numbers


class PolishError(RuntimeError):
    pass


NBSP = " "

# Function words used to tell French from English when no dictation language is
# set. French typography is the point of this app, so it must not depend on the
# user having found the language setting first.
_FRENCH_HINTS = re.compile(
    r"\b(je|tu|il|elle|nous|vous|ils|elles|le|la|les|un|une|des|du|de|et|est|sont|"
    r"que|qui|pas|plus|pour|dans|avec|sur|mais|donc|ce|cette|mon|ma|mes|son|sa|ses|"
    r"tout|toute|bien|aussi|tres|merci|bonjour|oui|non|alors|comme|quand|faire)\b",
    re.IGNORECASE,
)
_FRENCH_ACCENTS = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]", re.IGNORECASE)


def detect_language(text: str) -> str:
    """Best-effort ``fr``/``en`` guess from the text itself."""
    if _FRENCH_ACCENTS.search(text):
        return "fr"
    return "fr" if len(_FRENCH_HINTS.findall(text)) >= 2 else "en"


def resolve_language(language: str | None, text: str) -> str:
    """Which typography rules to follow: the setting, or the text when unset.

    Anything that is neither French nor English falls back to the English rules,
    which are the neutral ones (no space before double punctuation).
    """
    if language:
        return "fr" if language.lower().startswith("fr") else "en"
    return detect_language(text)


@dataclass(frozen=True)
class PolishOptions:
    style: str = "neutral"
    language: str | None = None
    cleanup_level: str = "medium"
    replacements: dict[str, str] | None = None
    snippets: dict[str, str] | None = None
    nonbreaking_spaces: bool = True
    trailing_space: bool = False
    # Seuil en dessous duquel un nombre dicté reste en toutes lettres, selon la
    # règle typographique française. 0 désactive la conversion.
    numbers_from: int = 10
    # Below this many words, leave the dictation alone: no leading capital, no
    # final period. That is what a search field or a chat box wants. 0 disables.
    short_text_words: int = 0


def finalize(text: str, options: PolishOptions) -> str:
    """Last touch shared by every polisher.

    The trailing space is for dictating twice in a row into the same field: the
    second sentence would otherwise land glued to the first one.
    """
    text = text.strip()
    return f"{text} " if text and options.trailing_space else text


class Polisher:
    def polish(self, text: str, options: PolishOptions | None = None) -> str:
        raise NotImplementedError


class HeuristicPolisher(Polisher):
    """Small local cleanup layer for usable dictation without an LLM."""

    # Hesitation sounds are not real words in either language, so they are safe
    # to strip whatever the dictation language is.
    _fillers = (
        "um",
        "uh",
        "erm",
        "hmm",
        "hum",
        "you know",
        "i mean",
        "euh",
        "heu",
    )
    # These *are* real words in their own language ("genre de", "I feel like"),
    # so they only go at the "high" level, and only for the language dictated.
    _fillers_high = {
        "en": ("like", "basically", "actually"),
        "fr": ("ben", "bah", "tsé", "genre"),
    }
    _spoken_punctuation = {
        "comma": ",",
        "period": ".",
        "full stop": ".",
        "question mark": "?",
        "exclamation mark": "!",
        "colon": ":",
        "semicolon": ";",
        "new line": "\n",
        "newline": "\n",
        "virgule": ",",
        "point d'interrogation": "?",
        "point d exclamation": "!",
        "deux points": ":",
        "point virgule": ";",
        "nouvelle ligne": "\n",
    }

    def polish(self, text: str, options: PolishOptions | None = None) -> str:
        if not text.strip():
            return ""
        options = options or PolishOptions()
        language = resolve_language(options.language, text)
        space = NBSP if options.nonbreaking_spaces else " "
        text = self._normalize_space(text)
        text = self._remove_fillers(text, language, options.cleanup_level)
        text = self._replace_spoken_punctuation(text)
        if language == "fr":
            # Avant l'espacement de la ponctuation : la règle qui protège
            # « 14:30 » et « https:// » a besoin de voir les chiffres.
            text = convert_numbers(text, options.numbers_from, space)
        # A handful of words is a search field or a chat box, not a sentence.
        sentence = options.short_text_words <= 0 or len(text.split()) >= options.short_text_words
        text = self._space_punctuation(text, language, space)
        if sentence:
            text = self._capitalize_sentences(text, language)
        text = self._apply_replacements(text, options.replacements or {})
        text = self._apply_snippets(text, options.snippets or {})
        if sentence:
            text = self._finish_sentence(text, options.style)
        if language == "fr":
            # Last, so the quote and apostrophe characters cannot break the
            # word-boundary matching of replacements and snippets above.
            text = self._french_quotes(text, space)
            text = self._french_apostrophes(text)
        return finalize(text, options)

    def _normalize_space(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()

    def _remove_fillers(self, text: str, language: str, cleanup_level: str) -> str:
        if cleanup_level == "light":
            fillers = ("um", "uh", "euh", "heu")
        elif cleanup_level == "high":
            fillers = self._fillers + self._fillers_high.get(language, ())
        else:
            fillers = self._fillers
        for filler in fillers:
            text = re.sub(rf"\b{re.escape(filler)}\b[ ,]*", "", text, flags=re.IGNORECASE)
        return text

    def _replace_spoken_punctuation(self, text: str) -> str:
        # Only replace a spoken mark when it stands as its own word, so words
        # like "commande" or "colonne" are not mangled into ", nde" / ": ne".
        for spoken, mark in self._spoken_punctuation.items():
            text = re.sub(rf"\b{re.escape(spoken)}\b", mark, text, flags=re.IGNORECASE)
        return text

    def _space_punctuation(self, text: str, language: str, space: str) -> str:
        # Drop whatever space precedes punctuation, including a previously
        # inserted non-breaking one, then re-add what the language calls for.
        text = re.sub(r"[^\S\n]+([,.;:!?])", r"\1", text)
        if language == "fr":
            # French puts a space before ; ! ? and :, but not before , and . —
            # skipping ":" in "https://" and "14:30", which are not punctuation.
            text = re.sub(r"(?<=\S)([;!?])", rf"{space}\1", text)
            text = re.sub(r"(?<=\S):(?![/\d])", f"{space}:", text)
        text = re.sub(r"([,;!?])(?=\S)", r"\1 ", text)
        text = re.sub(r"(:)(?=[^\s/\d])", r"\1 ", text)
        text = re.sub(r"(?<![A-Za-z0-9])\.(?=\S)", ". ", text)
        text = re.sub(r"(?<=[A-Za-z0-9])\.(?=[^A-Za-z0-9\s])", ". ", text)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"\n\s+", "\n", text)
        return text

    def _french_quotes(self, text: str, space: str) -> str:
        """Turn straight double quotes into « … », but only if they pair up."""
        if text.count('"') < 2 or text.count('"') % 2:
            return text
        return re.sub(r'"\s*([^"]*?)\s*"', rf"«{space}\1{space}»", text)

    def _french_apostrophes(self, text: str) -> str:
        """Curly apostrophe between letters: l'ami → l’ami, but not 'quoted'."""
        return re.sub(r"(?<=\w)'(?=\w)", "’", text)

    def _capitalize_sentences(self, text: str, language: str = "en") -> str:
        chars = list(text)
        capitalize_next = True
        for i, char in enumerate(chars):
            if char.isalpha() and capitalize_next:
                chars[i] = char.upper()
                capitalize_next = False
            elif char in "!?\n":
                capitalize_next = True
            elif char == ".":
                next_char = chars[i + 1] if i + 1 < len(chars) else ""
                capitalize_next = not next_char or next_char.isspace()
            elif not char.isspace():
                capitalize_next = False
        text = "".join(chars)
        if language != "fr":
            # Standalone "i" is the English pronoun; in French it is a letter
            # being spelled out, and upper-casing it is wrong.
            text = re.sub(r"\bi\b", "I", text)
        return text

    def _finish_sentence(self, text: str, style: str) -> str:
        if style in {"casual", "very-casual"}:
            return text
        if text.endswith((".", "!", "?", ":", ";")):
            return text
        if "\n" in text and re.search(r"\n\d+\. [^\n]+$", text):
            return text
        return text + "."

    def _apply_replacements(self, text: str, replacements: dict[str, str]) -> str:
        for raw, replacement in replacements.items():
            if not raw:
                continue
            text = re.sub(rf"\b{re.escape(raw)}\b", replacement, text, flags=re.IGNORECASE)
        return text

    def _apply_snippets(self, text: str, snippets: dict[str, str]) -> str:
        for name, value in snippets.items():
            if not name:
                continue
            text = re.sub(rf"\bslash {re.escape(name)}\b", value, text, flags=re.IGNORECASE)
            text = re.sub(rf"\binsert {re.escape(name)}\b", value, text, flags=re.IGNORECASE)
        return text


class OllamaPolisher(Polisher):
    def __init__(
        self,
        url: str = "http://127.0.0.1:11434",
        model: str = "llama3.1:8b",
        fallback: Polisher | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.fallback = fallback or HeuristicPolisher()
        self.timeout = timeout

    def polish(self, text: str, options: PolishOptions | None = None) -> str:
        if not text.strip():
            return ""
        options = options or PolishOptions()
        prompt = self._prompt(text, options)
        try:
            response = requests.post(
                f"{self.url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=self.timeout,
            )
            response.raise_for_status()
            polished = response.json().get("response", "").strip()
            if not polished:
                raise PolishError("Ollama returned an empty response")
            return finalize(self._strip_wrapping_quotes(polished), options)
        except Exception:
            return self.fallback.polish(text, options)

    _FRENCH_STYLES = {
        "neutral": "neutre",
        "formal": "formel",
        "casual": "décontracté",
        "very-casual": "très décontracté",
    }

    def _prompt(self, text: str, options: PolishOptions) -> str:
        if resolve_language(options.language, text) == "fr":
            return self._french_prompt(text, options)
        language = options.language or "the same language as the input"
        return f"""Rewrite this voice dictation into clean, ready-to-paste text.

Rules:
- Keep the original meaning.
- Do not add facts.
- Remove obvious filler words and false starts.
- Preserve technical terms, acronyms, commands, paths, and code-like text.
- Add natural punctuation and capitalization.
- Format obvious numbered or bulleted lists.
- Use a {options.style} style.
- Output only the final text in {language}.
{self._context_prompt(options)}

Dictation:
{text}
"""

    def _french_prompt(self, text: str, options: PolishOptions) -> str:
        style = self._FRENCH_STYLES.get(options.style, options.style)
        spacing = (
            "espace insécable avant ? ! ; et :"
            if options.nonbreaking_spaces
            else "espace avant ? ! ; et :"
        )
        return f"""Réécris cette dictée vocale en un texte propre, prêt à coller.

Règles :
- Garde le sens d'origine, n'ajoute aucune information.
- Supprime les hésitations et les faux départs.
- Conserve les termes techniques, les sigles, les commandes, les chemins et le code.
- Ponctue et mets les majuscules correctement.
- Respecte la typographie française : {spacing}, guillemets « », apostrophe ’.
- Mets en forme les listes numérotées ou à puces évidentes.
- Adopte un ton {style}.
- Ne renvoie que le texte final, en français, sans commentaire.
{self._french_context_prompt(options)}

Dictée :
{text}
"""

    def _french_context_prompt(self, options: PolishOptions) -> str:
        lines: list[str] = []
        if options.replacements:
            lines.append("- Utilise exactement ces orthographes quand elles s'appliquent :")
            for raw, replacement in options.replacements.items():
                lines.append(f"  - {raw} -> {replacement}")
        if options.snippets:
            lines.append("- Remplace les raccourcis dictés « slash NOM » ou « insert NOM » par :")
            for name, value in options.snippets.items():
                lines.append(f"  - {name} : {value}")
        return "\n".join(lines)

    def _context_prompt(self, options: PolishOptions) -> str:
        lines: list[str] = []
        if options.replacements:
            lines.append("- Apply these exact preferred spellings when relevant:")
            for raw, replacement in options.replacements.items():
                lines.append(f"  - {raw} -> {replacement}")
        if options.snippets:
            lines.append("- Expand snippet commands such as 'slash NAME' or 'insert NAME' with these values:")
            for name, value in options.snippets.items():
                lines.append(f"  - {name}: {value}")
        return "\n".join(lines)

    def _strip_wrapping_quotes(self, text: str) -> str:
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            return text[1:-1].strip()
        return text


def build_polisher(backend: str, ollama_url: str, ollama_model: str) -> Polisher:
    if backend == "heuristic":
        return HeuristicPolisher()
    if backend == "ollama":
        return OllamaPolisher(url=ollama_url, model=ollama_model)
    raise PolishError(f"Unknown polish backend: {backend}")
