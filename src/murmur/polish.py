from __future__ import annotations

import re
from dataclasses import dataclass

import requests


class PolishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolishOptions:
    style: str = "neutral"
    language: str | None = None
    cleanup_level: str = "medium"
    replacements: dict[str, str] | None = None
    snippets: dict[str, str] | None = None


class Polisher:
    def polish(self, text: str, options: PolishOptions | None = None) -> str:
        raise NotImplementedError


class HeuristicPolisher(Polisher):
    """Small local cleanup layer for usable dictation without an LLM."""

    _fillers = (
        "um",
        "uh",
        "erm",
        "hmm",
        "you know",
        "i mean",
        "euh",
        "heu",
    )
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
        text = self._normalize_space(text)
        text = self._remove_fillers(text, options.cleanup_level)
        text = self._replace_spoken_punctuation(text)
        text = self._space_punctuation(text)
        text = self._capitalize_sentences(text)
        text = self._apply_replacements(text, options.replacements or {})
        text = self._apply_snippets(text, options.snippets or {})
        text = self._finish_sentence(text, options.style)
        return text.strip()

    def _normalize_space(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()

    def _remove_fillers(self, text: str, cleanup_level: str) -> str:
        if cleanup_level == "light":
            fillers = ("um", "uh", "euh", "heu")
        elif cleanup_level == "high":
            fillers = self._fillers + ("like", "basically", "actually")
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

    def _space_punctuation(self, text: str) -> str:
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([,;!?])(?=\S)", r"\1 ", text)
        text = re.sub(r"(:)(?=[^\s/\d])", r"\1 ", text)
        text = re.sub(r"(?<![A-Za-z0-9])\.(?=\S)", ". ", text)
        text = re.sub(r"(?<=[A-Za-z0-9])\.(?=[^A-Za-z0-9\s])", ". ", text)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"\n\s+", "\n", text)
        return text

    def _capitalize_sentences(self, text: str) -> str:
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
            return self._strip_wrapping_quotes(polished)
        except Exception:
            return self.fallback.polish(text, options)

    def _prompt(self, text: str, options: PolishOptions) -> str:
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
