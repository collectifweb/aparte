# Fiabilisation Linux — septembre 2026

Plan accepté par Alexandre le 19 septembre, après l'audit
[`docs/audit-linux-2026-09-19.md`](../docs/audit-linux-2026-09-19.md).
Un commit par étape validée, documentation tenue à jour au même moment.

## Périmètre

Développer dans une copie isolée hors Syncthing, à partir de la branche Linux
après comparaison avec l'installation `~/murmur` et la branche distante.
Conserver intact le travail Mac et les fichiers `stale_server` non suivis du
dossier d'origine. Ne pas modifier le programme en cours d'utilisation pendant
la préparation. Pas de capture réelle ni de mise en veille automatique du poste.

## Lot 1 — dictée fiable (en cours)

- [x] Audit, consignes communes et reproductions documentés.
- [x] Branche Linux isolée, base vérifiée et suite de référence exécutée.
- [ ] Diagnostic audio réel et borné, sans texte dicté dans les journaux.
- [ ] Nettoyage garanti de l'enregistreur si publication de session impossible.
- [ ] Arrêt exclusif : une capture ne peut être traitée deux fois en parallèle.
- [x] Valeurs de Corrections/Raccourcis traitées comme texte littéral.
- [ ] Capture en échec récupérable dans un dossier privé pendant une heure :
      réessayer, supprimer et expiration explicite ; texte brut récupérable
      lorsque seule la mise en forme échoue.
- [ ] Tests de régression, revue indépendante, documentation et commits.
- [ ] Validation du correctif sur le poste puis après veille (distincte des
      tests synthétiques ; à coordonner avec l'usage du micro).

## Lots suivants

2. Protéger les données et le programme résident : journal du raccourci,
   validation des lectures HTTP, verrou de transcription, configuration et
   historique atomiques/coordonnés.
3. États cohérents du micro : quitter, capture à récupérer, ouvertures navigateur
   et import audio incompatibles.
4. Parcours : historique actualisé/effaçable, réglages immédiats, ponctuation,
   protection du texte édité.

## Règles de validation

Les reproductions de l'audit deviennent des tests de régression. Configuration,
état et cache sont isolés ; les périphériques, presse-papiers et notifications
réels ne sont pas utilisés. Vérifier les chemins réellement exécutés.
Une suite verte ne prouve pas la résolution du scénario matériel de retour de
veille : celui-ci doit être confirmé séparément.

## Journal des jalons

- 19 septembre : préparation enregistrée dans le dépôt d'origine : audit,
  consignes importées, scripts synthétiques et plan de mise en œuvre.
- Base Linux : `7ac99bc` (distante `Murmur/main`), code identique à l'installation
  `721b098` ; seul un complément documentaire les sépare. Copie isolée :
  `/tmp/aparte-linux-fiabilisation`, branche `fix/linux-dictee-fiable`.
  Suite initiale : **264 tests verts** (la suite du portage Mac en comptait 597).
- Vocabulaire littéral : cas sans déclencheur et insertion par correction ou
  raccourci couverts ; aucune modification de la configuration utilisateur.
