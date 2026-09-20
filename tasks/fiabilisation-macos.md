# Fiabilisation et livraison macOS — suivi du 19 septembre 2026

État : **correctifs locaux implémentés et vérifiés sous Linux ; validation
matérielle et distribution macOS encore ouvertes**.
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
- [x] Intégrer les correctifs communs de vocabulaire, Host HTTP, verrou
      d'inférence, configuration/historique et capture navigateur.
- [x] Résoudre les jonctions Mac à la main : garder les routes natives
      interdites via HTTP, les imports conditionnels et les boucles AppKit.
- [x] Adapter la récupération des captures/texte brut au contrôleur natif.
- [x] Tester refus disque, exceptions moteur/polissage, concurrence et
      enchaînement de dictées, puis suite complète isolée.

**Acceptation :** MAC-02 à 05, 10 et stockage de MAC-11 corrigés avec scénarios
reproductibles ; pas de régression Linux. Un commit ciblé par étape validée,
documentation dans le même jalon. Ne pas emporter les fichiers `stale_server`
préexistants sans décision distincte.

## Lot 2 — rendre les états et les sorties fiables

- [x] Fermeture : terminer le travail ou abandon explicitement choisi,
      conservation privée en cas d'échec ; pas de capture perdue implicitement.
- [x] Exposer dépassement de durée, débordement audio et dernière erreur.
- [x] Modèle : dépôt exact et cache complet, reprise après interruption,
      état partagé pour raccourci et navigateur ; sondage web résilient.
- [x] Définir la conservation réelle de l'historique temporaire sur Mac.
- [x] Réparer les écarts fonctionnels de MAC-15 : actions web disponibles,
      préférences de langue système, UTF-16, réglages relus par le menu,
      aperçu immédiat et conseils de réparation.
- [x] Autoriser la sortie d’un traitement bloqué une fois la capture préservée,
      sans collage tardif. En cas de panne de stockage, refuser de quitter et
      proposer de réessayer plutôt que perdre la capsule en mémoire.
- [ ] Mesurer les durées natives et définir les seuils d’avertissement ; pas de
      destruction arbitraire d’un fil de calcul Python.

**Acceptation :** états compréhensibles et cohérents après erreur ; récupération
possible ; aucun faux « prêt » dû à un cache vide ; aucun bouton durablement
bloqué après une erreur HTTP transitoire. Tests natifs pour Unicode/langue.

## Lot 3 — fermer le parcours d'installation

Dépend du verdict du lot 0 et du socle des lots 1–2.

- [ ] Implémenter la formula/tap versionnée : Python et dépendances compatibles
      avec les architectures promises, extras `whisper,recording,macos`, pas CUDA.
- [ ] Tester sur un compte neuf les prérequis Homebrew/outils Apple, sans supposer
      que Python, PortAudio ou les modèles sont déjà installés.
- [x] Publication du bundle avec restauration sur erreur, vérification de
      signature, réinstallation idempotente et message de réparation.
- [x] Ajouter au menu natif le choix/activation du raccourci avec retour arrière
      sur échec et la préparation explicite du modèle.
- [ ] Valider le premier lancement et les autorisations sur compte neuf, puis
      le raccourci par un véritable appui. Inscription acceptée ≠ raccourci prouvé.
- [x] Annoncer explicitement l’absence de démarrage à la connexion dans le README.
- [ ] Ajouter ultérieurement le démarrage natif avec opt-in après preuve du
      lanceur, sans le confondre avec l’intégration de bureau Linux.
- [ ] Vérifier mise à jour, relance nécessaire, désinstallation et données
      conservées. Aligner les commandes réellement disponibles et la doc.

**Acceptation :** un testeur suit uniquement la notice publique sur un compte
neuf, dicte, ferme, rouvre, met à jour et désinstalle sans intervention du
développeur ni commande de dépannage cachée.

## Lot 4 — automatisation et validation matérielle

À préparer pendant les lots précédents ; le passage complet suit le lot 3.

- [x] Préparer la CI macOS Apple Silicon sur push/PR : dépendances réelles,
      imports du paquet installé, clang/codesign, tests sans périphérique.
- [ ] Exécuter cette CI sur GitHub et conserver son résultat ; l’installation
      du paquet Python est couverte, celle de la formula attend le lot 0.
- [x] Préserver la CI Linux ; rendre les tests de langue indépendants de la
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

- [x] Consolider le suivi actuel, marquer l’audit comme historique et aligner
      README/CHANGELOG/consignes. Version inchangée : aucune release publiée.
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

Validation : 61 tests installation/bundle exécutés sous Linux, dont un test natif
clang/codesign ignoré. Ce dernier est ajouté pour le runner macOS.

### Captures, modèle, interface et automatisation

- Sauvegarde privée native avant inférence, texte brut avant polissage, verrou
  conservé de la création à la livraison ; récupération CLI et web après erreur.
- Fermeture coordonnée ; aucune insertion tardive après fermeture validée.
  Débordement audio et limite de durée visibles. Panne disque : capsule conservée
  ou fichier source laissé au chemin signalé, jamais présenté comme récupéré.
- Filtre Host sur les lectures HTTP, verrou d’inférence libéré même après une
  panne de fichier temporaire, capture navigateur exclusive et nettoyage des
  streams lors d’une erreur/ouverture tardive/fermeture de page.
- État du modèle fondé sur dépôt/révision/fichiers exacts, une préparation à la
  fois, reprise depuis le menu natif. Le chemin Mac faster-whisper utilise le
  snapshot local lors de l’inférence : l’HTTP ne lance pas son téléchargement.
- Copie web via le navigateur, bouton de collage système masqué sur Mac, réglages
  relus, langue des menus via Foundation, insertion UTF-16 corrigée. Le bandeau
  du modèle reprend après panne réseau et disparaît réellement après succès.
- Menu de raccourci avec retour arrière ; un backend Carbon par processus garde
  le callback vivant et ne consomme pas les événements étrangers.
- Lanceur de tests isolé et CI Linux/macOS ; la CI macOS n’a pas été exécutée
  dans cette intervention, qui dispose uniquement d’un hôte Linux.

**Vérification actuelle :** [preuve et limites](../docs/validation-macos-2026-09-19.md).
726 tests exécutés sous Linux, suite verte avec 1 test natif ignoré ; sélection
macOS : 471 tests avec ce même test ignoré (totaux non additionnables).

### Correspondance avec l’audit

| Constats | État après correction |
| --- | --- |
| MAC-01 à 05, MAC-10 et 11 | Correctifs intégrés avec tests du socle et des parcours concernés |
| MAC-06, MAC-08 | Ouverts : cible, installation neuve, TCC, distribution réelle |
| MAC-07 | Réglage natif livré ; essai physique du raccourci encore requis |
| MAC-09 | Sauvegarde avant fermeture et pas de livraison tardive ; kill brutal pendant capture hors garantie |
| MAC-12, MAC-13 | Cache exact, reprise et garde native/web pour faster-whisper ; poids réels à charger sur Mac |
| MAC-14 | Vérification + restauration ; essais codesign natifs préparés, pas exécutés ici |
| MAC-15 | Code et tests corrigés ; langue/Unicode/peripherals restent à confirmer nativement |
| MAC-16 | Récupération et CI préparées ; matrice matérielle et temps réels ouverts |

### Prochaine étape concrète

1. Exécuter `.claude/mac-validation/m7/` sur un Mac Apple Silicon récent ;
   consigner OS/Python/Homebrew/architecture, Finder, permissions et relances.
2. Déclencher la CI et suivre le premier résultat macOS. Tester le même commit
   sur compte neuf, avec texte synthétique, avant de déclarer un Mac pris en charge.
3. Sur ces preuves, choisir lanceur/signature puis implémenter la formula et
   son parcours de mise à jour/désinstallation. Le tap et la bêta ne sont pas publiés.
