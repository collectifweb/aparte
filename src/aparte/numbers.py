"""Nombres dictés en toutes lettres → chiffres, en français.

Whisper écrit déjà des chiffres une fois sur deux. L'enjeu n'est pas de tout
convertir, c'est de rendre le résultat prévisible : la même phrase dictée deux
fois doit s'écrire deux fois pareil.

La règle qui gouverne tout le module : dans le doute, ne rien toucher. Une suite
de mots qui ne forme pas un nombre valide ressort telle quelle.
"""

from __future__ import annotations

import re

NBSP = " "

_SMALL = {
    "zéro": 0,
    "zero": 0,
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "dix-sept": 17,
    "dix-huit": 18,
    "dix-neuf": 19,
}
# Septante, huitante, octante et nonante : la Belgique et la Suisse dictent
# aussi en français.
_TENS = {
    "vingt": 20,
    "vingts": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    "soixante": 60,
    "septante": 70,
    "huitante": 80,
    "octante": 80,
    "quatre-vingt": 80,
    "quatre-vingts": 80,
    "nonante": 90,
}
# Les seules dizaines qui prennent 10 à 19 comme unités : soixante-dix-sept se
# dit, vingt-douze non.
_TEENS_TENS = {60, 80}
_HUNDREDS = {"cent", "cents"}
_THOUSAND = {"mille", "milles"}
_SCALES = {"million": 10**6, "millions": 10**6, "milliard": 10**9, "milliards": 10**9}
_JOIN = "et"
_HOURS = {"heure", "heures"}
# « des mille et des cents » n'est pas une quantité.
_IDIOM_BEFORE = {"des", "les"}

# Million et milliard n'en font pas partie : ils ne sont pas absorbés dans la
# suite, ils la suivent, parce que « deux millions » s'écrit « 2 millions ».
_NUMBER_WORDS = set(_SMALL) | set(_TENS) | _HUNDREDS | _THOUSAND | {_JOIN}

_TOKEN = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)


def convert(text: str, minimum: int = 10, space: str = NBSP) -> str:
    """Réécrit en chiffres les nombres dictés en toutes lettres.

    ``minimum`` est le seuil en dessous duquel un nombre reste en lettres, selon
    la règle typographique française. À 0, la fonction ne fait rien. Les heures
    et les pourcentages ne suivent pas le seuil : ils s'écrivent toujours en
    chiffres.
    """
    if minimum <= 0 or not text:
        return text
    tokens = [(m.start(), m.end(), m.group()) for m in _TOKEN.finditer(text)]
    replacements = []
    index = 0
    while index < len(tokens):
        run = _run_at(text, tokens, index)
        if run is None:
            index += 1
            continue
        start, stop = run  # bornes de la suite, en indices de jetons
        replacement = _replace(text, tokens, start, stop, minimum, space)
        if replacement is None:
            index = stop
            continue
        end_token, written = replacement
        replacements.append((tokens[start][0], tokens[end_token][1], written))
        index = end_token + 1
    for begin, end, written in reversed(replacements):
        text = text[:begin] + written + text[end:]
    return text


def _run_at(
    text: str, tokens: list[tuple[int, int, str]], index: int
) -> tuple[int, int] | None:
    """Les bornes de la suite de mots-nombres qui commence à ``index``."""
    if not _is_number_word(tokens[index][2]) or tokens[index][2].lower() == _JOIN:
        return None
    stop = index + 1
    while stop < len(tokens) and _is_number_word(tokens[stop][2]):
        # Seule une espace peut séparer deux mots d'un même nombre : une virgule,
        # un point ou un retour à la ligne coupent la suite.
        if text[tokens[stop - 1][1] : tokens[stop][0]].strip(" "):
            break
        stop += 1
    while stop > index + 1 and tokens[stop - 1][2].lower() == _JOIN:
        stop -= 1  # un « et » final appartenait à la phrase, pas au nombre
    return index, stop


def _is_number_word(word: str) -> bool:
    """« vingt-deux » compte, et « porte-parole » non."""
    return all(part in _NUMBER_WORDS for part in word.lower().split("-"))


def _replace(
    text: str,
    tokens: list[tuple[int, int, str]],
    start: int,
    stop: int,
    minimum: int,
    space: str,
) -> tuple[int, str] | None:
    """Ce qu'il faut écrire à la place de la suite, et jusqu'où elle s'étend."""
    words = [tokens[i][2].lower() for i in range(start, stop)]
    if _is_idiom(text, tokens, start, words):
        return None
    value = _value(_expand(words))
    if value is None:
        return None

    after = tokens[stop][2].lower() if stop < len(tokens) else ""
    # Une heure s'écrit en chiffres quel que soit le seuil, et « une heure »
    # aussi, alors qu'un « une » seul ne se convertit jamais.
    if after in _HOURS and 0 <= value <= 24:
        return _hour(text, tokens, stop, value, space)
    if after == "pour" and _word_at(tokens, stop + 1) == "cent":
        return stop + 1, f"{value}{space}%"
    scale = _scale_after(tokens, stop)
    if scale:
        end, word = scale
        return end, f"{_written(value, space)} {word}"
    if words == ["un"] or words == ["une"]:
        return None
    if value < minimum:
        return None
    return stop - 1, _written(value, space)


def _is_idiom(text: str, tokens: list[tuple[int, int, str]], start: int, words: list[str]) -> bool:
    """« des mille et des cents », « pour cent » : des mots, pas des quantités."""
    before = _word_before(tokens, start)
    if before == "pour" and words[0] in _HUNDREDS:
        return True
    return len(words) == 1 and words[0] in (_HUNDREDS | _THOUSAND) and before in _IDIOM_BEFORE


def _word_before(tokens: list[tuple[int, int, str]], index: int) -> str:
    return tokens[index - 1][2].lower() if index > 0 else ""


def _word_at(tokens: list[tuple[int, int, str]], index: int) -> str:
    return tokens[index][2].lower() if 0 <= index < len(tokens) else ""


def _scale_after(tokens: list[tuple[int, int, str]], stop: int) -> tuple[int, str] | None:
    """« deux millions » s'écrit « 2 millions », pas « 2000000 »."""
    word = _word_at(tokens, stop)
    return (stop, tokens[stop][2]) if word in _SCALES else None


def _hour(
    text: str, tokens: list[tuple[int, int, str]], stop: int, hour: int, space: str
) -> tuple[int, str]:
    minutes = _run_at(text, tokens, stop + 1) if stop + 1 < len(tokens) else None
    if minutes:
        start, end = minutes
        value = _value(_expand([tokens[i][2].lower() for i in range(start, end)]))
        if value is not None and 0 <= value <= 59:
            return end - 1, f"{hour}{space}h{space}{value:02d}"
    return stop, f"{hour}{space}h"


def _expand(words: list[str]) -> list[str]:
    """Recolle ce que la dictée a séparé : quatre vingt dix sept → 80, 17."""
    parts: list[str] = []
    for word in words:
        parts.extend(word.split("-") if word not in _SMALL and word not in _TENS else [word])
    merged: list[str] = []
    index = 0
    while index < len(parts):
        following = parts[index + 1] if index + 1 < len(parts) else ""
        if parts[index] == "quatre" and following in {"vingt", "vingts"}:
            merged.append("quatre-vingt")
            index += 2
            continue
        if parts[index] == "dix" and following in {"sept", "huit", "neuf"}:
            merged.append(f"dix-{following}")
            index += 2
            continue
        merged.append(parts[index])
        index += 1
    return merged


def _value(words: list[str]) -> int | None:
    """La valeur d'une suite de mots-nombres, ou None si elle n'en forme pas une."""
    total = 0
    hundreds = tens = units = 0
    has_hundreds = has_tens = has_units = False
    thousands_done = False
    for word in words:
        if word == _JOIN:
            continue
        if word in _SMALL:
            value = _SMALL[word]
            if has_units or (has_tens and value >= 10 and tens not in _TEENS_TENS):
                return None
            units = value
            has_units = True
        elif word in _TENS:
            if has_tens or has_units:
                return None
            tens = _TENS[word]
            has_tens = True
        elif word in _HUNDREDS:
            if has_hundreds or has_tens or units > 9:
                return None
            hundreds = (units or 1) * 100
            has_hundreds, has_units, units = True, False, 0
        elif word in _THOUSAND:
            group = hundreds + tens + units
            if thousands_done:
                return None
            total += (group or 1) * 1000
            thousands_done = True
            hundreds = tens = units = 0
            has_hundreds = has_tens = has_units = False
        else:
            return None
    return total + hundreds + tens + units


def _written(value: int, space: str) -> str:
    """Le séparateur de milliers commence à cinq chiffres : une année reste
    « 2026 », pas « 2 026 »."""
    if value < 10000:
        return str(value)
    return f"{value:,}".replace(",", space)
