# Round 2 — Confirmation de consensus (Claude)

**Je confirme également le consensus, plus aucun désaccord substantiel de mon
côté.** Codex a émis `CONSENSUS_ATTEINT` au round-2 et a accepté mon argument sur le
seul point en désaccord partiel (le polissage va dans le worker, pas dans la
primitive `_transcribe_capture`). Revue du plan finalisé :

- Le **découpage M4 est validé** des deux côtés : contrôleur in-process, pas de
  self-HTTP, pas de portage de `session.py`, worker hors transcription. Rien
  n'oblige à réécrire le contrôleur pour brancher M5.
- La **passe de durcissement M4** (5 corrections chirurgicales + tests) est arrêtée
  et partagée. Les **reports** sont datés au bon lot (M5/M6/M8).

J'intègre les trois précisions de Codex, toutes justes :

1. **Capsule mutable par capture, pas seulement une liste.** La fermeture doit
   fermer sur un objet par capture portant `frames`, `frame_count`, `max_frames`,
   `active` (et idéalement `truncated`/`overflowed`), pour qu'un callback périmé ne
   puisse plus écrire dans *aucun* état d'instance après l'arrêt de sa capture — pas
   seulement dans la liste de frames. C'est ce qui rend le best-effort de
   `_close_stream` définitivement sûr.
2. **Une seule snapshot de `Settings` dans le worker**, utilisée pour polir **et**
   livrer : sinon on polirait avec un jeu de réglages et on insèrerait/historiserait
   avec un autre. Le helper partagé doit exprimer lisiblement le pipeline
   transcription brute → polissage → livraison, sans reconstruire un
   `argparse.Namespace` fragile.
3. **Câblage de `shutdown()` borné à M5** : dès que M5 rend la capture déclenchable
   dans l'application résidente, `run_desktop()` doit appeler `shutdown()` au
   shutdown applicatif ; le choix fin abandon-immédiat vs `join()` borné peut rester
   M5/M6.

Plan final consolidé écrit dans `docs/plan-portage-macos-m4-durcissement.md` (nom
distinct pour ne pas écraser `docs/plan-portage-macos-m4.md`, qui documente le M4
déjà livré). Prêt à exécuter la passe de durcissement au feu vert d'Alexandre.
