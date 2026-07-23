"""Retirer les génériques de sous-titrage que Whisper invente sur du silence.

Whisper a été entraîné sur des masses de vidéos sous-titrées. Quand l'audio se
tait — la fin d'une dictée, un blanc au milieu, un micro qui ne capte rien — il
ne rend pas le vide : il complète avec le générique qu'il a vu passer des
milliers de fois. « Sous-titres réalisés par la communauté d'Amara.org » est de
loin le plus fréquent en français.

Deux listes, parce que le risque de se tromper n'est pas le même :

- Les **phrases signées** portent un nom de domaine ou de diffuseur. Personne ne
  les dicte par accident, donc on les retire partout où elles apparaissent.
- Les **formules génériques** de fin de vidéo, elles, sont dictables : quelqu'un
  qui écrit le texte d'une vidéo peut très bien dire « merci d'avoir regardé
  cette vidéo ». On ne les retire que si elles constituent la **totalité** de la
  transcription — c'est-à-dire quand il n'y avait que du silence à transcrire.

La règle du module est celle de `numbers.py` : dans le doute, ne rien toucher.
Mieux vaut laisser passer une hallucination que manger une phrase dictée.
"""

from __future__ import annotations

import re

# Chaque entrée est une phrase entière et signée. Ne jamais y mettre un fragment
# comme « Amara.org » seul : « je cite Amara.org » est une dictée légitime.
SIGNED = (
    "Sous-titres réalisés par la communauté d'Amara.org",
    "Sous-titres réalisés para la communauté d'Amara.org",
    "Sous-titres réalisés par l'Amara.org",
    "Sous-titres réalisés par Amara.org",
    "Sous-titres par Amara.org",
    "Sous-titrage Société Radio-Canada",
    "Sous-titrage ST' 501",
    "Sous-titrage FR 2021",
    "par SousTitreur.com",
    "Subtitles by the Amara.org community",
)

# Retirées seulement quand elles sont tout le texte. Voir le docstring.
GENERIC = (
    "Merci d'avoir regardé cette vidéo",
    "Merci d'avoir regardé cette vidéo, à la prochaine",
    "Merci à tous d'avoir regardé cette vidéo",
    "Abonnez-vous",
    "Thanks for watching",
    "Thank you for watching",
)

_QUOTES = "['’‘`´]"
# Volontairement sans `\n` : un saut de ligne qui suit le générique appartient au
# texte dicté, pas au générique.
_TRAILING = r"[ \t.!?…,]*"


def _pattern(phrase: str) -> str:
    """Une phrase en motif tolérant : casse, apostrophe courbe ou droite, espaces."""
    parts = []
    for char in phrase:
        if char in "'’‘`´":
            parts.append(_QUOTES)
        elif char.isspace():
            parts.append(r"\s+")
        else:
            parts.append(re.escape(char))
    return "".join(parts)


# Le cœur emoji précède parfois « par SousTitreur.com », parfois non.
_SIGNED_RE = tuple(
    re.compile(r"[ \t]*[❤️♥]*[ \t]*" + _pattern(phrase) + _TRAILING, re.IGNORECASE)
    for phrase in SIGNED
)
_GENERIC_RE = tuple(
    re.compile(r"[\s❤️♥]*" + _pattern(phrase) + _TRAILING, re.IGNORECASE)
    for phrase in GENERIC
)


def strip(text: str) -> str:
    """Le texte débarrassé des génériques inventés. Une dictée normale ressort
    identique, à l'octet près."""
    if not text:
        return text
    cleaned = text
    for pattern in _SIGNED_RE:
        # Une espace, pas rien : le motif mange l'espace des deux côtés, et
        # retirer un générique au milieu recollerait les phrases voisines.
        cleaned = pattern.sub(" ", cleaned)
    # Reste les espaces en double que ce remplacement vient de créer. Les sauts
    # de ligne, eux, sont du contenu et ne doivent pas être écrasés.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if any(pattern.fullmatch(cleaned) for pattern in _GENERIC_RE):
        return ""
    return cleaned
