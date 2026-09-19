# Fiabilisation Linux — septembre 2026

> Installation ensuite effectuée par Alexandre et vérifiée : `~/murmur` est
> au commit de release `3f7e0da`, module et paquet **1.2.0**, arbre propre.
> Les retours de dictée réelle et après veille restent à recueillir. Le prochain
> chantier prévu est le lot 2 (journal privé, réglages et historique fiables).

> Mise à jour du 19 septembre : la [release GitHub v1.2.0](https://github.com/collectifweb/aparte/releases/tag/v1.2.0)
> est publiée comme dernière version stable, tag `v1.2.0` sur `3f7e0da`.
> La [CI Python 3.10–3.13](https://github.com/collectifweb/aparte/actions/runs/35455930154)
> est verte. Le suivi actualisé est sur `main`, commit documentaire `e658ce7`.
> Les mentions « pas encore publié » plus bas sont l'état du jalon précédent.
> L'installation `~/murmur` n'a pas été modifiée par cette publication.

Plan accepté par Alexandre le 19 septembre, après l'audit
[`docs/audit-linux-2026-09-19.md`](../docs/audit-linux-2026-09-19.md).
Un commit par étape validée, documentation tenue à jour au même moment.

## Périmètre

Développer dans une copie isolée hors Syncthing, à partir de la branche Linux
après comparaison avec l'installation `~/murmur` et la branche distante.
Conserver intact le travail Mac et les fichiers `stale_server` non suivis du
dossier d'origine. Ne pas modifier le programme en cours d'utilisation pendant
la préparation. Pas de capture réelle ni de mise en veille automatique du poste.

## Lot 1 — dictée fiable (implémenté, validation matérielle à faire)

- [x] Audit, consignes communes et reproductions documentés.
- [x] Branche Linux isolée, base vérifiée et suite de référence exécutée.
- [x] Diagnostic audio réel, lecture bornée, sans texte dicté dans le diagnostic.
- [x] Nettoyage garanti de l'enregistreur si publication de session impossible.
- [x] Arrêt exclusif : une capture ne peut être traitée deux fois en parallèle.
- [x] Valeurs de Corrections/Raccourcis traitées comme texte littéral.
- [x] Capture en échec récupérable dans un dossier privé pendant une heure :
      réessayer, supprimer et expiration explicite ; texte brut récupérable
      lorsque seule la mise en forme échoue.
- [x] Tests de régression, revue indépendante, documentation et commits.
- [ ] Validation du correctif sur le poste puis après veille (distincte des
      tests synthétiques ; à coordonner avec l'usage du micro).

## Lots suivants

2. Protéger les données et le programme résident : journal du raccourci,
   configuration et historique atomiques/coordonnés. La validation Host des
   lectures HTTP et la libération du verrou de transcription en cas d'erreur
   disque ont été avancées dans le lot 1, nécessaires à la récupération.
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
  Commit `a095669`.
- Sessions : **39 tests ciblés verts**, avec vrais enfants simulateurs (sans
  micro), erreur disque de publication et concurrence interprocessus. Diagnostic
  détaillé séparé du résumé utilisateur, fin du fils confirmée avant retrait du
  suivi. La cause matérielle après veille n'est toujours pas affirmée.
  Commit `fb706d8` ; raccordement de la transition CLI dans le jalon récupération.
- Récupération : raccourci, `dictate` et capture finale navigateur ; réessai,
  texte brut disponible, suppression et expiration initiale d'une heure.
  Verrou interprocessus commun au traitement et à la purge, fichiers privés,
  métadonnées corrompues et captures interrompues couvertes. La revue croisée a
  fait corriger la purge incomplète, sa reprise après panne temporaire et la
  capture navigateur non protégée initialement.
- Validation finale : **317 tests verts**, dont 39 sessions, 13 stockage de
  récupération, 21 CLI, 13 API/maintenance et 6 interface. Log isolé :
  `/tmp/aparte-audit-tests-0dea7xv1/unittest.log`. Aucun micro réel utilisé.
- Chromium : clair français à 1000 px et sombre anglais à 375 px, sans
  débordement ni erreur JavaScript. Puis navigation contre le vrai serveur HTTP
  sur un port éphémère, transcripteur simulé et polissage réel : liste, réessai,
  texte brut et suppression validés ; édition pendant calcul préservée, aucun
  appel au presse-papiers. Ces vérifications ne constituent pas un test du modèle
  Whisper ni du retour de veille.
- Documentation mise à jour : README (usage et limites de rétention), CHANGELOG,
  CLAUDE (invariants), DESIGN (panneau), rapport d'audit et présent suivi.

## Prochaine étape — essai sur le poste

Le lot est préparé sur `fix/linux-dictee-fiable`, pas encore fusionné, poussé ni
installé. `~/murmur` reste à `721b098` ; le portage Mac conserve son code initial.

1. Installer la branche Linux validée dans une fenêtre sans dictée active et
   redémarrer le processus résident, en conservant configuration et langue Auto.
   Garder `721b098` comme point de retour.
2. Vérifier une courte dictée depuis le raccourci, son arrêt et son insertion,
   puis le parcours navigateur. Vérifier qu'aucun enregistreur n'est laissé actif.
3. Après une vraie période d'inactivité puis un retour de veille choisi par
   Alexandre, répéter l'essai. En cas de refus, relever uniquement horodatage,
   code retour, périphérique et diagnostic ALSA ; le journal existant peut aussi
   contenir du texte dicté et ne doit pas être partagé intégralement.
4. Confronter ce diagnostic aux événements USB/audio du même instant avant de
   conclure à la cause. Ne pas changer automatiquement de micro, réinitialiser
   PipeWire ou forcer le français sur la base d'une simple corrélation.

La récupération ordinaire expire après une heure ; l'effacement physique attend
le passage de maintenance (chaque minute avec l'application ouverte, au prochain
lancement sinon). Une récupération active peut finir. Si le stockage lui-même
échoue, l'original est conservé hors de cette expiration ; `--keep-audio` conserve
aussi explicitement un original. Ces exceptions sont documentées dans le README.

## Repère depuis la branche macOS

Le lot 1 Linux est enregistré jusqu’au commit `12b9662` sur
`fix/linux-dictee-fiable` (copie de travail `/tmp/aparte-linux-fiabilisation`).
Cette branche partage le dépôt Git : ses commits restent disponibles même si
la copie temporaire est supprimée. Les changements fonctionnels et leur
documentation détaillée sont sur cette branche, sans fusion dans le portage.
