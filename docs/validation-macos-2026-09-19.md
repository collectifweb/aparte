# Fiabilisation macOS — vérification du 19 septembre 2026

Implémentation locale autorisée après l’[audit](audit-macos-2026-09-19.md).
[Suivi des lots et de leur statut](../tasks/fiabilisation-macos.md).

## Ce qui a été exécuté

Hôte Linux, Python 3.12. Copie isolée `/tmp/aparte-macos-fiabilisation` créée
à partir de `2013e29`, sans changement de branche dans l’arbre Syncthing et sans
modifier l’installation utilisée dans `~/murmur`. Reprise sélective du socle
Linux `ea4381c`, en préservant les chemins natifs Mac. Les deux fichiers
`stale_server` non suivis du dépôt d’origine restent hors des commits et des
totaux ci-dessous.

| Vérification | Résultat |
| --- | --- |
| `python3 scripts/run-tests.py` | 726 tests, suite verte, 1 ignoré car macOS nécessaire |
| `python3 scripts/run-tests.py --suite macos` | 471 tests, suite verte, même test ignoré |
| `python3 scripts/run-tests.py test_macos_desktop test_macos_install` | 61 tests, suite verte, même test ignoré |
| `python3 -m compileall -q src scripts tests` | Réussi |
| `node --check src/aparte/assets/app.js` et `i18n.js` | Réussi |
| `git diff --check` | Réussi |

Les sélections se recouvrent : **ne pas additionner leurs totaux**. Le test
ignoré est celui de la vraie signature du bundle avec clang/codesign. Les tests
Mac effectués ici utilisent des interfaces natives simulées. Les fichiers audio
et modèles de test sont synthétiques ; aucun micro, dictée personnelle,
presse-papiers réel ou réglage de démarrage n’est utilisé.

Scénarios de régression couverts : concurrence entre processus pour config,
historique et récupération ; panne de copie/écriture/publication ; verrou
d’inférence libéré ; sauvegarde avant inférence ; sauvegarde du brut ; abandon
d’un traitement bloqué après sauvegarde ; refus de sortie si conservation
impossible ; pas d’insertion tardive ; rollback du raccourci et survie du callback
Carbon ; snapshot modèle exact et refus du téléchargement HTTP ; transitions
et libération des streams navigateur ; restauration du bundle après échec.

## Vérification de l’interface

Navigateur Chromium/Brave local piloté par Playwright. Les ressources servies
sont les vrais fichiers du projet ; toutes les réponses API et le presse-papiers
sont factices. Parcours : voir une capture récupérable, demander son texte brut,
l’ouvrir explicitement dans l’éditeur, copier. Quatre configurations :

- clair 1280 × 800 ; sombre 1280 × 800 ;
- clair 800 × 600 ; sombre 390 × 844.

Résultat : aucune erreur JavaScript ni débordement horizontal ; collage système
masqué sur Mac, texte français copié intact. Inspection des captures effectuée.
Cela ne prouve pas les autorisations Safari, le véritable presse-papiers ou TCC.

Le détecteur Impeccable a été exécuté une fois : trois remarques concernent les
styles déjà présents (transition de largeur, taille 11 px, animation du modèle
indéterminé documentée dans DESIGN). Aucun de ces styles n’a été ajouté dans
cette intervention. Le contexte Impeccable ancien/sidecar reste à actualiser
séparément via `init` / `document` ; pas de migration de design implicite.

## Ce qui reste à prouver ou à livrer

- Job GitHub macOS **défini, pas exécuté ici** : paquet installé, véritables
  PyObjC/PortAudio/faster-whisper, clang/codesign sur Apple Silicon.
- Essais Finder et TCC, maintien des permissions après reconstruction et upgrade,
  raccourci réellement reçu, insertion Unicode dans les applications cibles,
  langue native, sources audio et veille/réveil.
- Compte neuf, matrice de support, stratégie finale du lanceur/signature,
  formula Homebrew, mise à jour et désinstallation utilisateur. Aucun tap,
  LaunchAgent ni bêta publiés. Absence d’autostart annoncée dans le README.
- Mesures de latence et chargement de vrais poids. Le contrôle du cache constate
  des fichiers requis non vides ; le moteur reste responsable de leur validité.
  La garde d’inférence sans téléchargement concerne le chemin faster-whisper
  macOS retenu ; les moteurs explicitement alternatifs conservent leur comportement.

## Limites de récupération connues

La capture native en cours reste en RAM jusqu’à l’arrêt : un kill brutal ou une
coupure de courant avant sauvegarde peut la perdre. Une capture du navigateur
jamais reçue par le serveur n’a pas de copie serveur. Les copies de secours ont
une échéance d’une heure ; le nettoyage tourne pendant que l’application est
ouverte et à la prochaine utilisation, jamais pendant son arrêt. L’historique
temporaire Mac est un fichier privé de 24 h, pas une garantie de disparition à la
fermeture de session. Si la sauvegarde échoue, le contrôleur retient sa capsule
ou la CLI conserve le fichier original et signale son chemin ; ces fichiers
exceptionnels ne sont pas tous gérés par la liste de récupération.

L’installation restaure l’ancien bundle après une erreur contrôlée. Un arrêt
brutal entre ses deux renommages peut nécessiter une restauration manuelle depuis
la sauvegarde ; aucun échange atomique de deux répertoires n’est prétendu.
