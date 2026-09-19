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

## Lot 2 — protection des données (en cours)

Travail autorisé par Alexandre après installation de la version 1.2.0. Branche
`fix/linux-donnees-fiables`, toujours dans `/tmp/aparte-linux-fiabilisation`.
L'application installée reste sur la release pendant la préparation.

- [x] Ancien journal local `/tmp/aparte-toggle.log` protégé : permissions 0664
      devenues 0600 après vérification du propriétaire et du type de fichier,
      sans lecture ni suppression de son contenu. Le raccourci 1.2.0 y écrit
      encore ; ce changement de permissions ne corrige pas à lui seul la collecte.
- [ ] Journal technique privé et borné, sans texte dicté ; migration conservatrice
      du raccourci connu sans déplacer sa touche ni toucher les autres commandes.
- [ ] Réglages : écriture atomique, fusion protégée entre processus, anciennes
      données préservées en cas d'erreur de sauvegarde.
- [ ] Historique : écritures/effacement coordonnés, fichier privé dès sa création,
      attente bornée pour ne pas suspendre la livraison de la dictée.
- [ ] Tests isolés avec concurrence réelle, revue croisée, documentation et
      commits à chaque jalon. Publication et installation du lot à suivre.

La protection Host des lectures HTTP et le déblocage de la transcription après
erreur disque ont déjà été livrés dans la version 1.2.0.

## Lots suivants

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

## Mise en service — retours d'usage en cours

Alexandre propose une mise en service suivie de retours d'usage, sans attendre
de reproduire tous les scénarios matériels. Version `1.2.0` préparée pour le
lot 1 (ajout de la récupération), déclarations et changelog alignés. La
publication GitHub a été explicitement autorisée par Alexandre et effectuée.
L'installation locale a ensuite été mise à jour par Alexandre. La mise à jour intégrée exige un
tag `v1.2.0` accessible depuis `main` ;
un push de commits sans tag ne sera pas proposé comme nouvelle version.
Les 17 tests du mécanisme de mise à jour passent après changement de version.
La commande CI est alignée sur la découverte locale validée (`-t tests`). La
[matrice distante Python 3.10–3.13](https://github.com/collectifweb/aparte/actions/runs/35455930154)
est verte sur le commit de version `3f7e0da`.

La [release GitHub v1.2.0](https://github.com/collectifweb/aparte/releases/tag/v1.2.0)
est publiée comme dernière version stable, avec notes françaises et tag annoté
sur `3f7e0da`, accessible depuis `main`. Aucun changement de l'installation
locale n'a été effectué lors de cette publication.

Le lot est préparé sur `fix/linux-dictee-fiable`. Les notes destinées à GitHub
sont dans [`docs/releases/v1.2.0.md`](../docs/releases/v1.2.0.md).
Installation vérifiée après le retour d'Alexandre : `~/murmur` est à `3f7e0da`,
module et paquet installés déclarent tous deux **1.2.0**, arbre propre. Le commit
supplémentaire de `main` est documentaire ; il ne manque aucun correctif de la
release sur le poste. Aucun essai micro ni retour de veille n'a été effectué
par l'agent. Le portage Mac conserve son code initial.

1. Installation 1.2.0 effectuée par Alexandre et vérifiée. Garder `721b098`
   comme point de retour.
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
