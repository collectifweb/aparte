# Fiabilisation et livraison macOS — plan proposé le 19 septembre 2026

État : **implémentation autorisée par Alexandre, en cours**.
Source : [audit macOS](../docs/audit-macos-2026-09-19.md), branche
`feat/portage-macos`, base `73b5317`. Alexandre a demandé l’implémentation après l’audit. Le travail reste local,
sans déploiement ni changement des installations utilisées.

## Objectif de sortie

Une personne sur un Mac explicitement pris en charge peut installer Aparté,
l'ouvrir depuis Finder, autoriser le micro et l'insertion, choisir et essayer
son raccourci, puis dicter sans perdre son travail sur une erreur récupérable.
Elle sait reconnaître capture, traitement, erreur et modèle non prêt. Une
mise à jour ne casse pas silencieusement les autorisations.

## Lot 0 — cible et preuve native de distribution

- [ ] Définir la matrice de support. Recommandation : Apple Silicon/macOS
      pris en charge par Homebrew pour la première distribution ; Intel ancien
      expérimental tant qu'un autre parcours n'est pas validé.
- [ ] Exécuter M7-0 depuis Finder sur un Mac de cette matrice : exec/enfant,
      identité des deux autorisations, signature, quarantaine, relance,
      reconstruction et upgrade Python/Homebrew.
- [ ] Enregistrer versions, architecture, commandes et verdicts sans dictée
      personnelle. Choisir le lanceur et la signature sur ces résultats.
- [ ] Si le parcours local ne tient pas ses garanties, comparer une distribution
      signée/notarisée avant d'investir davantage dans la formula.

**Acceptation :** preuve native reproductible de lancement et de maintien des
autorisations. Bloque les lots 3 et 5 ; le lot 1 peut avancer indépendamment.
Ne pas fabriquer de `.app` finale sur la seule réussite des mocks Linux.

## Lot 1 — reprendre le socle commun fiable

- [x] Créer une copie isolée hors Syncthing ; vérifier les remotes et comparer
      le vrai `main` récent, sans changer de branche dans l'arbre partagé.
- [ ] Intégrer les correctifs communs de vocabulaire, Host HTTP, verrou
      d'inférence, configuration/historique et capture navigateur.
- [ ] Résoudre les jonctions Mac à la main : garder les routes natives
      interdites via HTTP, les imports conditionnels et les boucles AppKit.
- [ ] Adapter la récupération des captures/texte brut au contrôleur natif.
- [ ] Tester refus disque, exceptions moteur/polissage, concurrence et
      enchaînement de dictées, puis suite complète isolée.

**Acceptation :** MAC-02 à 05, 10 et stockage de MAC-11 corrigés avec scénarios
reproductibles ; pas de régression Linux. Un commit ciblé par étape validée,
documentation dans le même jalon. Ne pas emporter les fichiers `stale_server`
préexistants sans décision distincte.

## Lot 2 — rendre les états et les sorties fiables

- [ ] Fermeture : terminer le travail ou abandon explicitement choisi,
      conservation privée en cas d'échec ; pas de capture perdue implicitement.
- [ ] Exposer dépassement de durée, débordement audio et dernière erreur.
- [ ] Modèle : dépôt exact et cache complet, reprise après interruption,
      état partagé pour raccourci et navigateur ; sondage web résilient.
- [ ] Définir la conservation réelle de l'historique temporaire sur Mac.
- [ ] Réparer les écarts fonctionnels de MAC-15 : actions web disponibles,
      préférences de langue système, UTF-16, réglages relus par le menu,
      aperçu immédiat et conseils de réparation.
- [ ] Définir une sortie d'un traitement anormalement long qui préserve la
      capture ; mesurer avant de fixer les seuils et le mécanisme d'annulation.

**Acceptation :** états compréhensibles et cohérents après erreur ; récupération
possible ; aucun faux « prêt » dû à un cache vide ; aucun bouton durablement
bloqué après une erreur HTTP transitoire. Tests natifs pour Unicode/langue.

## Lot 3 — fermer le parcours d'installation

Dépend du verdict du lot 0 et du socle des lots 1–2.

- [ ] Implémenter la formula/tap versionnée : Python et dépendances compatibles
      avec les architectures promises, extras `whisper,recording,macos`, pas CUDA.
- [ ] Tester sur un compte neuf les prérequis Homebrew/outils Apple, sans supposer
      que Python, PortAudio ou les modèles sont déjà installés.
- [ ] Publication du bundle avec restauration sur erreur, vérification de
      signature, réinstallation idempotente et message de réparation.
- [ ] Premier lancement : autorisations expliquées, préparation du modèle,
      choix/activation du raccourci et vérification par un véritable appui.
- [ ] Ajouter le démarrage à la connexion natif avec opt-in, ou annoncer
      explicitement son absence dans la première bêta. Ne pas confondre avec
      l'intégration de bureau Linux.
- [ ] Vérifier mise à jour, relance nécessaire, désinstallation et données
      conservées. Aligner les commandes réellement disponibles et la doc.

**Acceptation :** un testeur suit uniquement la notice publique sur un compte
neuf, dicte, ferme, rouvre, met à jour et désinstalle sans intervention du
développeur ni commande de dépannage cachée.

## Lot 4 — automatisation et validation matérielle

À préparer pendant les lots précédents ; le passage complet suit le lot 3.

- [ ] CI macOS sur chaque PR : dépendances natives réelles, imports PyObjC,
      compilation/signature du lanceur, installation du paquet/formula,
      tests sans périphérique et conservation des résultats.
- [ ] Préserver la CI Linux ; rendre les tests de langue indépendants de la
      locale du runner. La compilation sous gcc n'est pas la preuve clang.
- [ ] Essais manuels sur chaque combinaison OS/architecture annoncée :
      permissions, raccourci/clavier, quatre applications cibles, micro
      interne/USB/Bluetooth, changement de source, veille/réveil, fermeture.
- [ ] Mesures à froid et à chaud sur les mêmes fichiers synthétiques ou fournis
      volontairement pour le test ; langue/modèle identiques. Garder « Auto »
      comme choix utilisateur. Définir ensuite les délais acceptables.
- [ ] Vérifier mode hors ligne après préparation, téléchargement interrompu,
      erreurs de stockage, et mise à jour depuis la version précédente.

**Acceptation :** matrice de résultats datée sans échec bloquant ; échecs connus
explicitement exclus de la promesse publique. La CI ne remplace pas les essais
interactifs de permissions et de collage.

## Lot 5 — bêta limitée, puis publication

- [ ] Consolider une page d'état actuelle, archiver les consignes de lots
      devenues contradictoires, aligner README/CHANGELOG/versions.
- [ ] Distribuer une bêta à quelques testeurs sur les cibles annoncées ; relever
      erreurs et étapes techniques sans collecter les dictées par défaut.
- [ ] Corriger les problèmes bloquants observés et rejouer la matrice touchée.
- [ ] Préparer une release et une procédure de retour arrière ; demander
      l'autorisation de publication sur ce résultat concret.

**Acceptation :** aucune perte de dictée sur les scénarios d'échec couverts,
installation reproductible, permissions conservées sur l'upgrade testé,
limites de support visibles. Moteurs accélérés supplémentaires et refonte
d'interface ne sont pas des prérequis sans mesure qui les justifie.

## Jalons réalisés

### Stockage et vocabulaire

Reprise ciblée du socle Linux 1.3.0 dans `/tmp/aparte-macos-fiabilisation` :
réglages atomiques coordonnés, historique privé coordonné et remplacements
littéraux. Les réglages Mac `hotkey` et `beep` sont conservés. Sur Mac,
l’historique temporaire expire après 24 heures à la prochaine lecture/écriture ;
il reste un fichier sur disque lorsque l’application est arrêtée.

Validation : 92 tests ciblés verts sous Linux, dont concurrence entre processus,
pannes disque, migration et expiration Mac simulée. Aucune validation native
ni modification de l’installation Linux utilisée.

### Publication sûre du prototype `.app`

Construction sur le même volume que la destination, verrou installation /
désinstallation, signature vérifiée avant et après publication, restauration de
l’ancienne application en cas d’échec. Si la restauration échoue à son tour, la
sauvegarde reste disponible au chemin signalé. Un arrêt brutal entre les deux
renommages peut encore nécessiter cette restauration manuelle.

Le bundle contient les deux traductions et un lanceur indépendant de la locale ;
sa première reconstruction après ce changement peut nécessiter `--force` et de
réaccorder les autorisations. Le mode du lanceur et la signature restent ceux du
prototype : aucune décision M7-0 n’est déduite des simulations.

Validation : 60 tests installation/bundle exécutés sous Linux, dont un test natif
clang/codesign ignoré. Ce dernier est ajouté pour le runner macOS.
