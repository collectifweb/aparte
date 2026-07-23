# Round 3 — Confirmation de consensus (Claude)

**Je confirme également le consensus, plus aucun désaccord substantiel de mon
côté.**

## Ma revue du plan finalisé

J'ai relu le plan tel qu'il ressort du débat. Il tient, et pour trois raisons.

**Il traite une cause reproduite, pas une hypothèse.** Le point de départ était
une reconstruction que j'annonçais moi-même comme non prouvée. Elle l'est
maintenant : deux `toggle` concurrents laissent un `arecord` vivant que plus
aucune session ne référence. Le correctif C1 ferme cette course, C4 empêche de
signaler un PID recyclé, et le plan dit honnêtement ce qu'il ne ferme pas — un
lanceur tué entre `Popen()` et son nettoyage.

**Les correctifs sont ordonnés par ce que l'utilisateur constate.** A et B
règlent le symptôme décrit — presse-papiers écrasé, notification qui promet
avant d'agir. C règle la cause du blocage. D règle la source du charabia. E et F
sont de la dette, pas de la panne, et sont annoncés comme tels.

**Aucun correctif n'est spéculatif.** Pas de détecteur de charabia, pas de
quarantaine pour un état devenu impossible, pas de `has_insertable_text()` pour
un cas que personne n'a rencontré. `.strip()` reste le seuil du vide structurel.

## Ce que j'adopte de tes trois dernières précisions

Les trois sont justes, je les prends toutes :

1. **`_ARECORD_WAV_HEADER_BYTES = 44`** plutôt qu'un `_WAV_HEADER_BYTES`
   générique. La constante n'est vraie que pour le WAV que `session.py` demande
   à `arecord` ; un nom contextuel empêche qu'on la réutilise comme vérité WAV
   générale. Le commentaire dira que `-f S16_LE -c 1` est ce qui la rend vraie.
2. **Un test avec l'en-tête bouche-trou** (`0x40000000` trames) sur un fichier
   court, pour verrouiller la décision : si quelqu'un revient un jour à
   `wave.open()`, ce test tombe.
3. **`os.fsencode()`** dans `_recorder_alive()`, plus exact que
   `str(...).encode("utf-8")` pour l'encodage du système de fichiers. J'ajoute
   aussi la vérification que la ligne de commande contient bien `arecord` : deux
   signatures valent mieux qu'une, et ça coûte une condition.

## Ce que je retiens du débat

Trois de mes positions initiales étaient fausses, et c'est toi qui les as
cassées :

- supprimer le `.wav` d'une session morte — destruction de données au moment
  exact où l'utilisateur veut la récupérer ;
- `_process_exists()` présenté comme protection contre le recyclage de PID,
  alors qu'il en est aveugle ;
- `max_recording_seconds` dans `EDITABLE_FIELDS`, qui n'aurait créé aucun
  contrôle dans l'interface.

Une des tiennes l'était aussi, et la mesure l'a tranchée : `wave.open()` lit un
en-tête que `arecord` ne finalise qu'en sortant proprement.

Le plan final consolidé est dans [docs/plan-dictee-vide.md](../../plan-dictee-vide.md).

CONSENSUS_CONFIRME
