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

## Lot 2 — protection des données (publié en 1.2.1)

Travail autorisé par Alexandre après installation de la version 1.2.0. Branche
`fix/linux-donnees-fiables`, toujours dans `/tmp/aparte-linux-fiabilisation`.
L'application installée reste sur la release pendant la préparation.

- [x] Ancien journal local `/tmp/aparte-toggle.log` protégé : permissions 0664
      devenues 0600 après vérification du propriétaire et du type de fichier,
      sans lecture ni suppression de son contenu. Le raccourci 1.2.0 y écrit
      encore ; ce changement de permissions ne corrige pas à lui seul la collecte.
- [x] Journal technique privé et borné, sans texte dicté ; migration conservatrice
      du raccourci connu sans déplacer sa touche ni toucher les autres commandes.
- [x] Réglages : écriture atomique, fusion protégée entre processus, anciennes
      données préservées en cas d'erreur de sauvegarde.
- [x] Historique : écritures/effacement coordonnés, fichier privé dès sa création,
      attente bornée pour ne pas suspendre la livraison de la dictée.
- [x] Tests isolés avec concurrence réelle, revue croisée, documentation et
      commits à chaque jalon.
- [x] Publication de la release 1.2.1.
- [x] Installation de la 1.2.1 vérifiée en lecture seule sur le poste.
- [ ] Retours d'usage, notamment après veille.

La [release GitHub 1.2.1](https://github.com/collectifweb/aparte/releases/tag/v1.2.1)
est publiée comme dernière version stable, après autorisation d'Alexandre.
Le tag annoté `v1.2.1` pointe sur `5a5ad64`, accessible depuis `main`.
Les [notes de version](../docs/releases/v1.2.1.md), les deux déclarations et le
changelog sont alignés. Les 17 tests de mise à jour passent après changement de
version ; la [CI Python 3.10–3.13](https://github.com/collectifweb/aparte/actions/runs/35462467495)
est verte sur le commit publié. L'installation `~/murmur` a ensuite été vérifiée
en lecture seule : module 1.2.1, arbre propre ; seul un complément documentaire
de `main` lui manque. Aucun test matériel n'a été effectué par l'agent.

La protection Host des lectures HTTP et le déblocage de la transcription après
erreur disque ont déjà été livrés dans la version 1.2.0.

Jalon stockage : **24 tests réglages et 22 tests historique verts**, incluant
vrais processus concurrents, lecteurs pendant publication, pannes disque,
initialisation/migration et effacement concurrents. Revue croisée effectuée ;
le faux échec possible après publication a été supprimé. L'ancien fichier reste
intact sur les pannes avant remplacement. Verrous bornés à cinq secondes pour
les réglages et une demi-seconde pour l'historique ; ce dernier peut abandonner
une opération pour préserver la livraison. Tests d'historique en `spawn`, sans
fork d'un processus ayant déjà des threads HTTP. Les garanties ne couvrent ni
les anciennes versions ni les outils externes qui ignorent ces verrous.
Commit du jalon stockage : `cd96aef`.

Jalon journal et intégration : **370 tests Linux verts**, log isolé
`/tmp/aparte-audit-tests-90iiwxpj/unittest.log`. Les tests couvrent les sorties
Python, natives, enfants et `atexit`, les pannes disque et les commandes
personnalisées. La revue indépendante a reproduit une fuite après restauration
des sorties, puis confirmé sa disparition avec le silence permanent du
processus de raccourci. Les tests d'intégration vérifient aussi qu'une erreur
d'historique n'empêche pas la copie et qu'un refus de sauvegarde est signalé par
l'API sans perdre les réglages précédents.

Lecture seule sur le poste : la commande Cinnamon du slot `custom3`, touche
`<Super>space`, est reconnue ; la migration propose
`/home/alexandre/murmur/.venv/bin/python -m aparte toggle --target paste --hotkey`.
Aucune modification du raccourci ni ouverture du micro pendant ce contrôle.
Le remplacement du wrapper prendra effet au lancement de la version 1.2.1 sur
le poste ; l'ancien journal, maintenant privé, reste conservé. Aucun test réel
après veille n'est revendiqué.

## Lot 3 — états du micro et fermeture (validé localement, non publié)

Branche `fix/linux-etats-micro`, base `76db28c`, dans la copie isolée
`/tmp/aparte-linux-fiabilisation`. L'installation utilisée reste inchangée.

- [x] Distinguer au repos, capture réellement vivante, traitement, audio à
      récupérer et état inconnu ; même source pour le menu, le diagnostic et
      `toggle --status`.
- [x] Quitter arrête la capture du raccourci puis conserve son audio dans la
      récupération d'une heure. Aucune transcription ni insertion au départ.
      Si l'arrêt ou la sauvegarde échoue, l'application reste ouverte ; si un
      traitement est actif, elle demande d'attendre.
- [x] Les traitements CLI/HTTP sont suivis par des verrous vivants, sans texte,
      audio ni PID dans leurs marqueurs. Un processus mort ne bloque pas la
      fermeture. La mise à jour garde l'exclusion jusqu'au redémarrage.
- [x] SIGINT/SIGTERM suivent la fermeture protégée, avec ou sans barre système.
- [x] Un corps HTTP bloqué sans progression expire après 30 secondes et libère
      son traitement ; ce délai réseau ne limite pas le temps du modèle.
- [x] Navigateur : ouverture/arrêt explicites, doubles clics exclus, import et
      capture incompatibles, ressources libérées après erreur ou navigation,
      permissions et réponses tardives ignorées après navigation.
- [x] La mise à jour et la capture du même onglet s'excluent.
- [x] Revue croisée et vérifications ciblées : vrais processus synthétiques,
      HTTP sur port éphémère, signaux envoyés uniquement à des processus de test.
- [x] Validation finale : **419 tests Linux verts**, documentation actualisée
      dans le même jalon. Log isolé :
      `/tmp/aparte-audit-tests-xwhmpxvu/unittest.log`.
- [ ] Publication d'une version contenant ce lot, puis validation sur le poste.

**Limite de responsabilité :** l'icône et « Quitter » suivent la capture du
raccourci. Le micro du navigateur appartient à l'onglet : utiliser Arrêter ou
fermer cet onglet. Quitter le programme Python ne ferme pas les micros d'autres
onglets. Aucun protocole de coordination entre onglets n'est ajouté ici. Une
interruption forcée (SIGKILL/crash) ne passe pas par la fermeture protégée.

Chromium vérifié en français clair sur bureau (1000 px) et en anglais sombre
sur mobile (375 px), API et audio simulés : ouverture lente, arrêt différé,
absence de double capture, pistes libérées avant fermeture du contexte audio,
aucun débordement ni erreur JavaScript. Le WAV envoyé reste correct même si la
fermeture du contexte échoue. Contrôle syntaxique JavaScript et détecteur visuel
mécanique sans erreur. Pas de vérification matérielle du micro ni de l'icône GTK.

## Lot 4 — parcours (à faire)

Historique actualisé/effaçable, réglages immédiats, ponctuation et protection du
texte édité contre les réponses asynchrones. La validation du retour de veille
reste menée en parallèle par les retours d'usage, sans diagnostic matériel
présumé.

## Compléments d’usage — retour du 19 septembre 2026 (à réaliser)

Alexandre souhaite traiter ultérieurement la refonte de l’interface et un
indicateur flottant visible depuis l’application où il dicte. Il rapporte des
traitements pouvant durer 60 à 80 secondes, utilise le modèle `small` et décrit
son ordinateur comme chargé. Ces durées et cette charge sont rapportées, pas
mesurées ici ; leur cause n’est pas établie. Aucune perte sur deux dictées
successives n’a été signalée : c’est un scénario préventif à vérifier.

- [ ] **Priorité au garde-fou des dictées successives**, à intégrer au lot 4 :
      reproduire A en traitement puis capture/arrêt de B, y compris polissage
      lent, erreurs, délégation indisponible et changement d’application cible.
      Vérifier conservation des deux résultats, ordre de livraison et absence de
      collision du presse-papiers. La protection du lot 3 contre Quitter ne
      constitue pas une file d’attente de dictées.
      Proposition initiale : refuser clairement un nouveau départ tant que la
      précédente n’est pas livrée, sans couper une capture déjà active. Une
      véritable file d’attente, si retenue ensuite, devra conserver séparément
      chaque audio/résultat et rendre explicite la destination du collage.
- [ ] **Mesurer les délais par étape** : attente, chargement à froid,
      transcription, polissage et livraison ; durée audio, moteur et CPU/GPU
      effectivement utilisés, charge au moment de l’essai. Passer par le parcours
      réel de l’application, comparer à réglages égaux, sans journaliser le texte
      ou exploiter un audio personnel sans accord. Garder la langue Auto ; aucun
      changement de modèle avant d’avoir localisé le coût et évalué la qualité.
- [ ] **Indicateur flottant léger** : écoute → attente éventuelle → transcription
      → polissage → prêt/inséré, avec erreur ou récupération explicite. Montrer
      l’étape réelle et le temps écoulé, sans pourcentage inventé. Ne pas voler le
      focus ni intercepter la saisie dans l’application cible. Première version
      sans nouvelle transcription d’aperçu, pour ne pas ajouter de calcul pendant
      les lenteurs. Reprendre le [lot 5B historique](todo.md#lot-5b--fenêtre-flottante-au-raccourci-clavier-planifié-le-2207-pas-commencé)
      avec ce périmètre révisé ; ses hypothèses techniques datées sont à revérifier.
- [ ] **Refonte globale de l’interface**, chantier distinct à cadrer ensuite avec
      Alexandre, après les protections et la visibilité du traitement.

Lecture du code du lot 3 : `cli.toggle_dictation` peut redémarrer une capture
après retrait de la session précédente, même si son traitement continue.
`desktop._handle_transcribe` sérialise l’inférence sur son modèle partagé, mais
`cli.transcribe_path` effectue ensuite le polissage et `_finish_dictation` la
livraison dans chaque processus CLI. Ce verrou ne garantit donc pas l’ordre de
bout en bout. Ce constat est une lecture du code, pas une reproduction matérielle
ni une preuve que la première dictée serait systématiquement perdue.

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
