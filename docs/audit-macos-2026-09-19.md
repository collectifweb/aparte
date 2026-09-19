# Audit du portage macOS — 19 septembre 2026

**Verdict : le prototype de dictée Mac est substantiel, mais la branche n'est
pas prête à être distribuée à des utilisateurs ordinaires.** Les priorités sont
la protection des dictées, la reprise des correctifs communs déjà livrés sous
Linux, puis la preuve du parcours d'installation et d'autorisation sur un Mac
Apple Silicon récent. Une refonte générale n'est pas justifiée par cet audit.

Plan exécutable : [fiabilisation et livraison macOS](../tasks/fiabilisation-macos.md).

## Périmètre et preuves

- Arbre audité : `~/Apps-coding/Aparte`, branche `feat/portage-macos`, HEAD
  `73b5317`, version déclarée `1.1.3`. Remote effectif : `Murmur`.
- Clone Linux comparé en lecture seule : `~/murmur`, `main`, HEAD `ea4381c`,
  version `1.3.0`. La référence `main` de l'arbre Mac est ancienne : elle ne
  suffit pas pour savoir quels correctifs existent déjà.
- Les deux fichiers non suivis `src/aparte/stale_server.py` et
  `tests/test_stale_server.py` préexistaient et sont préservés.
- Trois explorations indépendantes recoupées : installation, fonctionnement
  natif, modèle/HTTP. Aucun correctif applicatif ni réglage utilisateur changé.
  Aucun audio personnel lu, écouté ou transcrit, aucun micro réel ouvert.
- **Exécution actuelle : 597 tests passent** sous Linux/Python 3.12 avec locale
  française, configuration et dossiers XDG isolés. Ce total inclut le test
  `stale_server` non suivi. Première tentative : 14 erreurs dues aux sockets
  interdites dans le bac à sable ; relance autorisée avec localhost : suite verte.
  Journal conservé : [`unittest.log`](archives/audit-macos-2026-09-19/unittest.log).
- **Simulations actuelles :** vrais handlers Python, contrôleur Mac et
  gestionnaires JavaScript, dépendances natives remplacées et données synthétiques.
  Elles prouvent les scénarios décrits, pas leur fréquence sur Mac.
- **Validation Mac historique uniquement :** comptes rendus M8 et M6 du
  25 juillet, Big Sur 11.7.11 Intel, Python 3.11.9. Ni Apple Silicon récent,
  ni installation Homebrew finale, ni identité des autorisations de la `.app`
  validés par une preuve retrouvée. Aucun Mac n'a été piloté pendant cet audit.

## État d'avancement réel

| Élément | État constaté |
| --- | --- |
| Séparation Linux/macOS, capture PortAudio, permissions | Implémentées ; tests et essais historiques |
| Raccourci global, insertion, typographie française | Implémentés ; essais historiques TextEdit/LibreOffice |
| Barre de menus, minuteur, démontage normal | Implémentés et validés historiquement sur Intel |
| Téléchargement visible du modèle | Implémenté ; défauts de reprise et de détection ci-dessous |
| Lanceur natif, icône, `install-app` | Code présent ; stratégie d'autorisation non tranchée nativement |
| Formula Homebrew, installation reproductible | Absente de l'arbre audité ; M7d non livré |
| Démarrage à la connexion Mac | Non implémenté ; M7g non livré |
| Mise à jour Homebrew | État et commande indiqués, mais chaîne d'installation finale non validée |
| Qualité commune depuis les releases Linux récentes | Correctifs importants absents de cette branche |

Le découpage des modules, les captures séparées contre les callbacks tardifs,
le travail hors boucle AppKit, les verrous d'enregistrement/inférence distincts
et les routes HTTP d'insertion désactivées sur Darwin sont de bons acquis.
Les anciens plantages Carbon et le silence faute de demande micro ont déjà été
corrigés : ils ne sont pas comptés comme défauts ouverts.

## Constats prioritaires

P1 = bloque une diffusion fiable, perte de contenu ou protection des données.
P2 = fonctionnalité trompeuse, récupération insuffisante ou qualité à corriger.
La priorité exprime l'impact, pas une fréquence mesurée.

### MAC-01 — P1 : le socle commun n'a pas reçu les correctifs Linux récents

**Lu et comparé.** `pyproject.toml:7`, `src/aparte/__init__.py`, historique Git
du clone Linux. Les commits Linux `a095669` (vocabulaire littéral), `12b9662`
(récupération), `cd96aef` (stockage) et `37d5286` (états du micro et interface)
contiennent des réponses à plusieurs défauts encore présents ici.

**Conséquence :** publier directement la branche Mac réintroduirait des défauts
déjà réparés ailleurs. Les mentions de releases Linux dans la documentation ne
signifient pas que leur code a été intégré.

**Correction :** intégrer le socle commun dans une copie isolée, avec résolution
explicite des points Mac. Ne pas remplacer les modules mixtes par leurs versions
Linux entières ; le contrôleur Mac exige une adaptation de la récupération.

### MAC-02 — P1 : perte de capture après erreur de transcription ou de polissage

**Simulé.** `macos_recording.py:287–339` retire la capture du contrôleur puis
supprime systématiquement le WAV en `finally`, même avant toute livraison.
Résultat injectant une erreur moteur : état `error`, WAV absent, capture absente,
aucun texte livré. Le commentaire affirmant que le texte est déjà dans l'historique
ne couvre pas les erreurs antérieures à la livraison.

**Correction :** conservation privée et bornée des captures en échec, reprise ou
suppression explicite ; texte brut récupérable si seul le polissage échoue.

### MAC-03 — P1 : une valeur de vocabulaire peut casser toutes les dictées

**Reproduit avec le vrai polisseur.** `polish.py:229–241` interprète les valeurs
comme des remplacements regex. Une seule entrée contenant `\s+` lève
`bad escape \s`, même si le déclencheur n'est pas prononcé, dans Corrections
comme dans Raccourcis. Combiné à MAC-02, l'audio disparaît.

**Correction :** reprise du correctif littéral déjà livré sous Linux et test
sur le parcours natif Mac, avec secours du texte brut.

### MAC-04 — P1 : lectures HTTP sensibles sans validation de l'hôte

**Simulé sur le handler Darwin.** `desktop.py:273–294` sert l'historique avec un
`Host` et un `Origin` étrangers : réponse 200 contenant le texte synthétique.
Le POST équivalent est correctement refusé en 403. Les routes POST désactivées
sur Mac ne protègent pas ces lectures.

**Limite :** aucune exploitation DNS/navigateur complète ni fuite réelle établie.
**Correction :** reprendre la validation Host de toutes les lectures sensibles,
en conservant la protection Origin des écritures.

### MAC-05 — P1 : le navigateur peut afficher le repos avec une capture active

**Simulé avec les vrais gestionnaires JS.** `assets/app.js:77–90,258–275` :
deux clics pendant l'ouverture créent deux flux ; après Stop, un flux reste
actif et `recordState` vaut `idle`. L'import pendant une capture remet aussi
l'écran au repos sans fermer celle-ci. Ce défaut concerne la dictée navigateur,
pas une preuve de défaillance du raccourci natif.

**Correction :** reprendre les états d'ouverture/fermeture exclusifs du socle
Linux, les exclusions d'actions incompatibles et le nettoyage des flux obsolètes.

### MAC-06 — P1 : l'installation grand public reste non démontrée

**Lu.** `tasks/todo.md:1300–1366`, `macos_install.py`,
`.claude/mac-validation/m7/README.md`. Aucun résultat M7-0 retrouvé ; les choix
lanceur `exec`/enfant et signature restent des hypothèses. La formula n'est pas
livrée. `platform_dispatch.py:34–48` refuse encore l'intégration de bureau sur
Darwin ; `install-app` existe séparément, mais pas l'autostart Mac.

**Correction :** exécuter M7-0 sur la cible retenue, avec refus puis accord des
deux autorisations, relance, réinstallation et mise à jour. Seulement ensuite
figer la formula et le parcours. Un test Linux avec `codesign` simulé ne valide
ni Gatekeeper, ni l'identité vue par macOS, ni la conservation des permissions.

### MAC-07 — P1 : le parcours neuf ne configure pas le raccourci principal

**Lu.** `config.py:53–56` initialise `hotkey` vide ; `cli.py:514–531` installe
et ouvre sans l'activer. La barre de menus (`macos_tray.py:377–388`) ne permet
pas de lancer une capture ; l'inscription n'a lieu qu'au démarrage.

**Conséquence :** les deux commandes envisagées n'aboutissent pas à la dictée
globale : il manque le choix du raccourci, son activation et un véritable appui
de vérification. `registered: true` ne prouve pas l'absence de conflit.

**Correction :** choix explicite au premier lancement par un parcours natif,
activation puis essai guidé, sans autoriser une route web à déclencher le micro.

### MAC-08 — P1 : la seule cible testée ne valide plus le choix Homebrew

**Source externe actuelle vérifiée.** Homebrew classe désormais les Mac Intel
en Tier 3 et a cessé les nouvelles bottles Intel. Les essais Big Sur restent
utiles pour le prototype, mais ne prouvent pas une installation simple avec la
chaîne de distribution choisie. [Niveaux de support Homebrew](https://docs.brew.sh/Support-Tiers),
[annonce 7.0.0 du 13 septembre 2026](https://brew.sh/2026/09/13/homebrew-7.0.0/).

**Correction proposée :** première cible de distribution Apple Silicon avec
macOS encore pris en charge par Homebrew ; Intel ancien en compatibilité
expérimentale tant qu'un parcours séparé n'est pas prouvé. Cette recommandation
ne retire pas le code Intel : le périmètre produit reste à décider.

### MAC-09 — P1/P2 : « Quitter » abandonne le travail en cours

**Lu et simulé.** `macos_tray.py:504–507`, `macos_recording.py:188–214,303–305`.
Une capture en cours est jetée ; un traitement en cours n'est ni joint ni
annulé avant terminaison. Simulation d'un moteur suspendu : `shutdown()` rend
`True` alors que le worker daemon reste vivant et l'état reste `processing`.

**Correction :** terminer puis quitter, ou abandon explicitement choisi ; dans
tous les cas, préserver le travail récupérable. Fermer le micro ne suffit pas
à démontrer une fermeture qui protège la dictée.

### MAC-10 — P2 : transcription bloquée après une simple erreur disque

**Simulé.** `desktop.py:470–488` prend le verrou avant la création du temporaire,
hors du `try` qui le libère. ENOSPC donne 500 ; l'aperçu suivant renvoie
`busy: true` sans travail actif. L'échec de suppression peut également empêcher
la libération. Le raccourci Mac partage ce verrou (`desktop.py:579–581`).

**Correction :** reprendre le nettoyage garanti du socle Linux ; protéger
acquisition, écriture et suppression indépendamment des erreurs de fichier.

### MAC-11 — P2 : réglages et historique insuffisamment protégés

**Reproduit.** `config.py:212–231`, `history.py:64–90` : lecture pendant une
sauvegarde → `JSONDecodeError` ; erreur d'écriture → configuration vide ; deux
producteurs synchronisés → perte d'au moins une entrée d'historique.

**Correction :** reprendre les écritures atomiques et la coordination du socle
Linux ; inclure le serveur, le raccourci natif et les commandes dans les tests.
Complément Mac : `history.py:28–30` utilise un fichier temporaire même lorsque
la persistance est désactivée. La promesse « mémoire, effacé à la déconnexion »
de `assets/i18n.js:172` n'est pas garantie par ce code sur macOS. Définir et
tester la durée réelle de conservation, puis aligner les textes.

### MAC-12 — P2 : le modèle peut être annoncé prêt sans être utilisable

**Simulé.** `model_download.py:160–162` juge suffisant un dossier `snapshots`
vide. `diagnostics.py:458–463` accepte même un dossier `small.en` lorsqu'on
demande `small`, car la recherche est une sous-chaîne.

**Correction :** vérifier le dépôt exact et les fichiers nécessaires localement,
gérer le cache partiel et partager le même verdict entre diagnostic, interface
et moteur. Tester un téléchargement interrompu puis un redémarrage hors ligne.

### MAC-13 — P2 : la préparation du modèle ne reprend pas correctement

**Simulé pour le navigateur, lu pour le natif.** `assets/app.js:886–894` cesse
définitivement de sonder après une erreur réseau. Après un état `downloading`,
le bouton reste désactivé sans nouveau timer, même si le téléchargement finit.
Le raccourci natif, lui, n'interroge pas cet état (`macos_recording.py:174–186`) :
la protection du bouton web ne couvre pas le chemin principal.

**Correction :** reprise bornée des sondages avec état explicite ; garde commune
de disponibilité et action native de relance. Éviter une seconde tentative
implicite de chargement pendant que le premier téléchargement travaille.

### MAC-14 — P2 : remplacement de l'application sans retour arrière

**Simulé.** `macos_install.py:146–150` supprime l'ancien bundle avant le
déplacement du nouveau. Avec `--force`, une erreur de copie injectée laisse
l'ancien bundle absent. Ce constat ne signifie pas que la signature échoue :
la panne est simulée après la construction.

**Correction :** préparer sur le volume de destination, conserver l'ancien
bundle jusqu'à publication réussie, restaurer sur erreur ; contrôler la signature
du résultat installé et garder une procédure de désinstallation complète.
La langue choisie depuis `LANG` entre aussi dans le contenu du bundle
(`macos_desktop.py:105–173`) : une reconstruction sous une autre locale change
ses octets. Inclure ce cas dans la preuve de conservation des autorisations ;
préférer des ressources localisées stables à un bundle différent par langue.

### MAC-15 — P2 : défauts d'état, d'insertion et de langue

- **Audio incomplet non signalé, simulé :** `macos_recording.py:245–258,312–339`
  retient `overflowed`/`truncated` mais ne les expose jamais. Un débordement
  injecté produit une livraison normale sans avertissement. Publier ces états.
- **Bouton Insérer inopérant sur Mac, lu :** `assets/app.js:302–305` appelle
  `/api/paste`, volontairement refusé sur Darwin (`desktop.py:49,372`). Adapter
  les actions affichées aux capacités ; conserver l'interdiction HTTP.
- **Longueur Unicode incorrecte, argument simulé :** `macos_insert.py:70–75`
  passe 3 pour `A😀B`, qui compte 4 unités UTF-16. Effet natif exact à vérifier
  avec PyObjC ; le collage Cmd+V habituel n'est pas concerné. Corriger le
  comptage et les frontières de segments après test du pont réel.
  [Référence Apple de l'API](https://developer.apple.com/documentation/coregraphics/cgevent/keyboardsetunicodestring(stringlength:unicodestring:)).
- **Langue native déduite seulement du terminal, simulé :**
  `macos_tray.py:127–131` rend l'anglais sans variables `LANG`/`LC_*`.
  Tester Finder sur un compte francophone et lire les préférences macOS.
- **Réglage aperçu non appliqué immédiatement, simulé :** désactiver la case
  puis sauvegarder laisse `livePreview` vrai (`assets/app.js`, sauvegarde des
  réglages). Synchroniser l'état mémoire et tester la dictée suivante.
- **Historique du menu périmé, lu :** `_copy_last()` utilise le réglage de
  persistance capturé au démarrage (`macos_tray.py:498`), tandis que le worker
  relit la configuration. Un changement peut faire copier une ancienne dictée.
- **Conseils CLI obsolètes, lus :** `_sounddevice()` propose seulement
  `.[macos]`, sans l'extra `recording` qui manque ; `cli.py:614–615` conseille
  `skhd → aparte toggle` alors que cette commande est refusée sur Mac.
  Les plans annoncent également `uninstall-app`, alors que la commande livrée
  est `install-app --remove`.

### MAC-16 — P2 : récupération et validation native restent trop limitées

**Lu et simulation d'attente.** Un moteur qui ne revient pas laisse le
contrôleur en `processing`, sans annulation ni reprise ; les nouvelles dictées
sont refusées. Aucun blocage réel de Whisper sur Mac n'a été reproduit ici.
Prévoir une récupération qui préserve la capture, sans tuer arbitrairement un
thread Python ; mesurer les délais avant de choisir une limite de traitement.

La CI (`.github/workflows/ci.yml`) ne tourne que sur Ubuntu, au push sur `main`
ou en PR vers `main`, avec les seules dépendances core/dev. Elle ne valide pas
les dépendances natives réellement installées. Le succès local des 597 tests
n'est donc pas un feu vert pour une release Mac.

## Limites et essais indispensables

Pas de panne affirmée faute d'essai. À mesurer sur les Mac retenus : autorisations
au nom d'Aparté depuis Finder ; refus puis accord ; upgrade sans perte silencieuse
de permissions ; clavier français et conflits du raccourci ; insertion dans Mail,
TextEdit, navigateur et application Electron ; micro interne/USB/Bluetooth ;
débranchement, changement de périphérique, veille/réveil ; arrêt au plafond ;
fermeture pendant capture/traitement ; première installation sans réseau ;
téléchargement interrompu ; performances à froid/chaud.

Comparer les performances à langue et modèle identiques. **Conserver le choix
« Auto » d'Alexandre.** Le moteur CPU actuel n'est pas, à lui seul, un défaut :
un éventuel travail Metal/MLX vient après mesures sur Apple Silicon et après
fiabilisation, sans changer simultanément tout le portage.

## Reproduire sans données personnelles

Les probes de cet audit sont dans
[`archives/audit-macos-2026-09-19/`](archives/audit-macos-2026-09-19/README.md).
Les scénarios partagés réutilisent les scripts isolés de l'audit Linux :
`backend.py` et `interface.cjs`. Les simulations natives remplacent les accès
matériels ; ne pas interpréter leur réussite comme une validation AppKit/TCC.

Les descriptions M5 « pas commencé », les restes M8 déjà clos et les consignes
M7 contradictoires doivent être consolidés lors des lots : le code et les preuves
datées priment sur les anciennes cases. Ne pas annoncer une progression en
pourcentage : la dernière preuve d'installation conditionne toute la diffusion.
