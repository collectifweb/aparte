# Audit du produit Linux — 19 septembre 2026

> Ce rapport décrit l'état initial, avant correctifs. Leur avancement et leurs
> validations sont consignés dans le [plan de fiabilisation](../tasks/fiabilisation-linux.md).

**Conclusion : plusieurs défauts du produit Linux sont reproductibles, dont des
pertes de dictée et des captures laissées ouvertes. Le message « micro occupé »
est trompeur ; la cause exacte des incidents après inactivité reste à établir.**

L'audit couvre le raccourci global, l'enregistrement Linux, la transcription,
la mise en forme, la configuration, l'historique, le serveur local et les parcours
de l'interface. Trois sous-agents ont exploré ces domaines ; les reproductions
ont été recoupées par l'agent principal. Le portage macOS n'est pas l'objet de
cet audit. Aucun correctif fonctionnel, changement de réglage ou déploiement
n'a été effectué.

## 1. Compréhension du projet et cible réellement utilisée

Aparté est une application Python de dictée locale, centrée sur Linux et la
typographie française. Le parcours principal est le raccourci global : capture
ALSA, transcription Whisper, polissage, historique de secours, insertion dans
l'application active. Le processus résident conserve le modèle pour accélérer
la transcription. Le navigateur sert aussi à dicter, importer, régler et relire,
mais sa capture est distincte de celle du raccourci. L'interface est en HTML,
CSS et JavaScript sans compilation ni bibliothèque.

| Cible | État vérifié pendant cet audit |
| --- | --- |
| Développement `~/Apps-coding/Aparte` | `feat/portage-macos`, HEAD `c346b3e`, version déclarée `1.1.3` |
| Référence locale `main` de ce dépôt | `ce56ce5` ; elle est plus ancienne que l'installation utilisée |
| Installation `~/murmur` | `main`, HEAD `721b098`, version déclarée `1.1.5`, arbre propre |
| Raccourci Cinnamon | `<Super>space` exécute `~/murmur/.venv/bin/python -m aparte toggle --target paste`, avec redirection de sortie vers `/tmp/aparte-toggle.log` |
| Programme résident | Même environnement `~/murmur/.venv`, lancé le 18 septembre à 13:21 ; sortie et erreurs vers `/dev/null` |
| Installation Python | Le fichier `.pth` éditable pointe vers `~/murmur/src` |

Les fichiers `session.py`, `audio.py`, `cli.py`, `history.py`, `config.py`,
`polish.py`, `tray.py` et `assets/app.js` de l'installation sont identiques à ceux
de la référence locale `main`. `desktop.py` a évolué depuis cette référence :
ses quatre défauts signalés ici ont aussi été reproduits sur le clone installé.
Ces défauts ne sont donc pas attribués au portage Mac.

Deux fichiers non suivis existaient avant l'audit : `src/aparte/stale_server.py`
et `tests/test_stale_server.py`. Ils ont été préservés.

## 2. Micro « occupé » : preuves et limites

### Observations réelles sur le poste

- Micro choisi dans Aparté : `plughw:CARD=Mini,DEV=0`, Razer Seiren Mini USB.
- Système audio : PulseAudio fourni par PipeWire `1.0.5`.
- Au relevé, le Razer était présent ; ses nœuds audio étaient `SUSPENDED` et
  aucun détenteur de périphérique de capture n'a été trouvé par `fuser`.
  Cela décrit ce relevé, pas l'instant d'un incident antérieur.
- La source système par défaut était la webcam Xiongmai, pas le Razer.
  Revenir aveuglément au micro « par défaut » pourrait donc changer le micro.
- Le journal noyau montre une sortie de veille le 18 septembre à 09:42:20,
  puis l'apparition du Razer sur le bus USB à 10:30:43 et de la webcam à 10:30:48.
  Ces événements ne sont pas concomitants et ne prouvent pas une causalité.
- `/tmp/aparte-toggle.log` contient **20 lignes d'erreur** portant toutes le
  même message générique. Elles ne contiennent ni horodatage ni erreur ALSA.
- Le dossier d'exécution contient **16 anciens fichiers `toggle-*.wav`**, datés
  du 9 au 18 septembre, dont un de **9 600 044 octets**, compatible avec le
  plafond de 300 secondes à 16 kHz mono S16_LE. Leur contenu n'a pas été écouté,
  transcrit ou copié. Leur présence ne révèle pas la cause de leur abandon.

### Ce que le code permet de conclure

`session.py:318` jette le diagnostic d'`arecord` avec `stderr=DEVNULL`.
`session.py:334–348` attribue ensuite tout démarrage raté à une possible
occupation. **Reproduction exécutée :** un faux enregistreur qui répond
« ALSA: No such device » produit aussi « Another application may be holding
the microphone ». L'occupation n'a donc pas été diagnostiquée.

Le ramassage d'enregistreurs oubliés existe déjà (`session.py:218–280`). Il ne
couvre que les processus sans session, âgés de plus de deux secondes. Il envoie
SIGINT puis attend jusqu'à une seconde ; il ne garantit pas que le micro a été
libéré. La documentation du projet rapporte déjà quatre orphelins fin juillet,
sans cause initiale établie.

Le chemin Linux ne comporte pas de traitement spécifique du retour de veille,
ni de nouvelle tentative conditionnée à une erreur audio identifiée. Le nom
`CARD=Mini` n'est pas un simple index `card2` susceptible de changer.

**Hypothèses encore ouvertes :** indisponibilité temporaire USB/ALSA,
concurrence d'accès au périphérique, ou enregistreur Aparté oublié. Les journaux
actuels ne permettent pas de les départager pour les incidents signalés.

Le choix `plughw` contourne le partage habituellement assuré par le serveur
audio. Les plugins ALSA distinguent conversion et partage de capture ; `dsnoop`
est précisément un mécanisme de partage. Cela motive l'évaluation d'une capture
via le serveur audio, sans établir que ce choix cause les incidents présents.
[Documentation ALSA](https://www.alsa-project.org/alsa-doc/alsa-lib/pcm_plugins.html).

La documentation WirePlumber précise que désactiver la suspension laisse le
périphérique ALSA occupé. Ce n'est donc pas un correctif à appliquer au hasard
à une application qui ouvre directement ce périphérique.
[Documentation WirePlumber](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html#node-properties).

## 3. Défauts confirmés par reproduction isolée

Les lignes ci-dessous désignent l'arbre de développement audité. P1 : risque
de perte de dictée, confidentialité ou capture non maîtrisée. P2 : fiabilité ou
comportement incorrect à corriger après les urgences. Ces priorités expriment
l'impact, pas une fréquence mesurée.

### A01 — P2 : diagnostic micro trompeur

**Source :** `src/aparte/session.py:315–348`. Décrit et reproduit ci-dessus.
Conserver l'erreur réelle, le code de sortie, le périphérique et un horodatage,
sans enregistrer le texte ni l'audio dans les journaux de diagnostic.

### A02 — P1 : une erreur détruit la dictée avant toute récupération

**Source :** `src/aparte/cli.py:418–433` ; sur `main`, `:363–382`.
La session est retirée, puis le WAV supprimé dans `finally`, même lorsque
transcription ou polissage échoue. La notification reste « Transcription… ».

**Preuve :** exception de transcription injectée avec WAV synthétique ; après
l'appel, `audio.exists()` vaut faux, et aucune notification d'échec n'a été émise.
La notification d'erreur d'insertion ne couvre pas ce scénario antérieur.

**Correction proposée :** conservation temporaire privée et bornée de la capture
en échec, notification explicite, reprise ou suppression volontaire ; si seul le
polissage échoue, rendre le texte brut récupérable.

### A03 — P1 : erreur de publication, enregistreur laissé vivant

**Source :** `src/aparte/session.py:315–333`.
Après `Popen`, une exception dans `_claim_session()` ne passe pas par le
nettoyage réservé au retour `False`.

**Preuve :** enfant réel simulant l'enregistreur, sans ouverture audio ; erreur
ENOSPC injectée lors de la publication. L'enfant est encore vivant et aucun
fichier de session n'existe. Le simulateur est arrêté par le banc d'essai.

**Correction proposée :** garantir le nettoyage de l'enfant pour toute exception
après son lancement. Ce défaut est une source possible d'orphelins ; il n'est
pas démontré comme origine des fichiers trouvés sur le poste.

### A04 — P2 : deux arrêts peuvent prendre la même dictée

**Source :** `src/aparte/session.py:352–369`.
Deux processus lisant la session avant sa suppression peuvent tous deux
l'arrêter et recevoir le même WAV.

**Preuve :** deux appels concurrents synchronisés après lecture ont tous deux
réussi et retourné le même chemin. La double insertion ou la suppression du
fichier sous le second lecteur sont des conséquences possibles, pas observées
sur une vraie application cible pendant cet audit.

**Correction proposée :** prise exclusive de la session pour arrêt et traitement,
comme l'atomicité déjà utilisée à la publication du démarrage.

### A05 — P1/P2 : « Quitter » et l'icône décrivent mal le micro

**Sources :** `src/aparte/tray.py:134–150`, `src/aparte/session.py:134–138`.
Quitter le tray arrête le serveur mais laisse le processus de capture détaché.
Inversement, une session dont le processus est mort mais dont le son est
récupérable affiche encore « micro ouvert ».

**Preuves :** enfant simulateur toujours vivant après `_quit()` ; puis, avec
processus mort et une seconde de WAV, titre « Aparté — microphone open ».

**Correction proposée :** arrêter et préserver la capture à la fermeture ;
distinguer enregistrement, traitement et capture à récupérer dans l'état partagé.

### A06 — P1 : l'interface peut laisser une capture ouverte à l'état repos

**Sources :** `src/aparte/assets/app.js:258–275`, `:77–84`, `:107–128`.

- Deux clics pendant l'attente de `getUserMedia` lancent deux captures : la
  seconde écrase la référence à la première. Après Stop, une capture subsiste.
- L'import audio est autorisé pendant une capture avant le premier aperçu,
  ou sans aperçu. Sa fin remet le bouton au repos sans fermer la capture.

**Preuves :** vrais gestionnaires JavaScript exécutés avec API navigateur
simulées, sur la branche actuelle et `main`. Double clic : deux demandes,
une capture encore active après Stop, état `idle`, session nulle. Import :
capture active, état `idle`. Aucun périphérique réel n'a été ouvert.

**Correction proposée :** réserver synchroniquement l'ouverture et la fermeture,
interdire l'import incompatible, nettoyer toute capture obsolète ou partiellement
initialisée. Ce défaut navigateur n'est pas assimilé au problème du raccourci.

### A07 — P1 : une entrée de vocabulaire peut casser toutes les dictées

**Source :** `src/aparte/polish.py:233–241`.
Les valeurs de corrections et de raccourcis sont interprétées comme modèles de
remplacement de regex, alors que l'utilisateur fournit du texte littéral.

**Preuve :** une valeur `\s+` dans une seule entrée provoque `bad escape \s`,
même pour « bonjour tout le monde », sans prononcer le déclencheur. Les deux
types d'entrées ont été testés avec le vrai `HeuristicPolisher`. Combiné à A02,
ce réglage peut faire perdre l'audio de chaque dictée.

**Correction proposée :** fournir un remplacement littéral par fonction à
`re.sub`, et préserver le résultat brut si le polissage échoue.

### A08 — P1 : l'historique peut être lu avec un hôte étranger

**Source :** `src/aparte/desktop.py:273–294`, garde POST `:366–369`, `:431–456`.
La validation de l'hôte protège les écritures, pas les lectures sensibles.

**Preuve :** vrai handler avec données synthétiques : GET `/api/history` avec
Host/Origin `rebound.attacker.invalid:8765` retourne 200 et la dictée ; le POST
équivalent retourne 403. Reproduit aussi dans le clone installé.

**Limite :** la garde serveur manquante est confirmée ; une exploitation DNS
et navigateur de bout en bout n'a pas été exécutée et dépend des protections
du navigateur. Aucune fuite réelle n'est affirmée.

**Correction proposée :** valider l'hôte pour toutes les routes sensibles,
en conservant la garde d'origine des écritures.

### A09 — P2 : une erreur temporaire bloque les transcriptions suivantes

**Source :** `src/aparte/desktop.py:470–488` ; installé `desktop.py:399–417`.
Le verrou est pris avant les opérations de fichier qui précèdent le `try`.
Un échec de création/écriture/fermeture peut donc laisser le verrou acquis ;
un échec de suppression dans le `finally` peut aussi empêcher sa libération.

**Preuve :** ENOSPC à la création → 500 ; aperçu suivant → `busy: true` alors
qu'aucune transcription n'est en cours. Reproduit sur les deux copies.

**Correction proposée :** englober toute la section par un nettoyage garanti
du verrou, indépendant de l'échec éventuel de suppression du temporaire.

### A10 — P2 : sauvegarde non atomique des réglages

**Source :** `src/aparte/config.py:217–230` ; installé `:200–215`.
Le vrai fichier est tronqué avant réécriture.

**Preuves :** lecture par `load_config()` pendant la sauvegarde →
`JSONDecodeError` ; ENOSPC pendant l'écriture → fichier définitivement vide.
Les réglages et le vocabulaire peuvent ainsi devenir indisponibles.

**Correction proposée :** temporaire voisin puis remplacement atomique,
et coordination des modifications concurrentes.

### A11 — P2 : perte d'historique entre deux producteurs

**Source :** `src/aparte/history.py:58–62`, `:74–80`.
Lecture-modification-écriture sans verrou interprocessus et temporaire commun
`history.json.tmp`.

**Preuve :** deux `record()` contemporains ont produit une seule entrée au lieu
de deux. Reproduit dans les deux copies avec textes synthétiques.

**Correction proposée :** verrou couvrant toute la transaction et temporaire
unique ; préserver le caractère non bloquant pour la livraison du texte.

### A12 — P2 : réglage enregistré, état de page périmé

**Source :** `src/aparte/assets/app.js:493–507`.
Sauvegarder « Aperçu » n'actualise pas `livePreview`. Le texte de confidentialité
basé sur `historyPersist` peut également rester périmé jusqu'au rechargement
des réglages.

**Preuve :** après décochage et sauvegarde simulée réussie, case fausse mais
variable `livePreview` vraie, sur branche courante et `main`.

**Correction proposée :** appliquer aux états locaux la configuration renvoyée.

### A13 — P2 : ponctuation française « point virgule » incorrecte

**Source :** `src/aparte/polish.py:111–115`.
« virgule » est traité avant « point virgule ».

**Preuve avec le vrai polisseur :** « bonjour point virgule au revoir » devient
« Bonjour point, au revoir. »

**Correction proposée :** traiter les expressions longues avant leurs fragments.

## 4. Confidentialité : défaut réel du paramétrage du poste

### A14 — P1 : le raccourci conserve le texte dans un journal peu protégé

Le raccourci installé redirige sortie et erreurs vers `/tmp/aparte-toggle.log`.
La sortie standard de la CLI contient la dictée. Le fichier existe, contient
du texte de dictée et porte le mode **0664**, donc autorise la lecture aux
autres comptes locaux disposant de l'accès normal à `/tmp`.

C'est une configuration du raccourci observée sur ce poste, pas un comportement
par défaut attribué à toutes les installations. Aucun contenu privé n'est
reproduit dans ce rapport. La présence d'autres lecteurs ou une fuite réelle
n'ont pas été établies.

**Action proposée :** journal technique privé, borné et sans dictées ; traiter
explicitement le journal existant. Aucune suppression, redirection ou permission
n'a été changée pendant cet audit.

## 5. Trous d'usage et améliorations

Ces points sont issus de la lecture du code et des parcours ; ils ne sont pas
tous des reproductions dans un navigateur réel.

1. **Récupération après incident.** Proposer « Réessayer », « Copier le texte
   brut », « Supprimer », avec conservation limitée clairement annoncée.
   L'état actuel oppose suppression immédiate sur erreur (A02) et résidus sans
   parcours de récupération ; une politique cohérente manque.
2. **Historique au retour sur l'onglet.** `loadRecent()` ne tourne qu'à
   l'initialisation (`app.js:608`, `:908`). Une dictée au raccourci n'actualise
   pas la page déjà ouverte ; rafraîchir au retour au premier plan permettrait
   de retrouver le texte après un collage raté.
3. **Effacement explicite.** `history.clear()` n'est exposé ni en interface ni
   en commande. Désactiver la persistance change de fichier mais n'efface pas
   les anciennes dictées sur disque. Prévoir une action et un choix clair.
4. **Un état micro cohérent.** Afficher le périphérique réellement utilisé,
   l'enregistrement, le traitement et la récupération, pour le raccourci et la
   page. Une sélection de micro dans Aparté n'affecte pas le micro du navigateur.
5. **Insertion dans l'application voulue.** Le bouton web envoie immédiatement
   le collage vers la fenêtre active, qui peut être le navigateur cliqué.
   La nécessité d'un délai ou d'une sélection de destination est à valider dans
   un essai d'usage. Le mode terminal global impose aussi des changements manuels.
6. **Texte en cours de modification.** Un polissage asynchrone peut remplacer
   les modifications tapées depuis son lancement (`app.js:132–135`). Protéger
   la version éditée ou demander avant de l'écraser ; pas de reproduction dédiée.
7. **Diagnostics réellement utiles.** Actuellement, présence d'un outil et
   disponibilité du périphérique sont trop facilement confondues. Montrer la
   dernière erreur concrète et une action adaptée, sans ouvrir le micro à l'insu
   de l'utilisateur et sans collecter le contenu des dictées.

Autres points à examiner ensuite : la délégation de transcription ne distingue
pas un profil CLI fourni par `APARTE_CONFIG` de celui du serveur ; l'éditeur
n'a pas de libellé accessible permanent ; le dossier de repli `/tmp/aparte-uid`
n'impose pas lui-même un mode privé. Ces observations de code n'ont pas toutes
fait l'objet d'une reproduction complète et ne sont pas mélangées aux résultats
confirmés de la section 3.

## 6. Vérifications et portée de la conclusion

- **597 tests existants passent**, y compris les tests Mac et le fichier de test
  non suivi déjà présent. Exécution sous Python 3.12, locale `fr_CA.UTF-8`, avec
  configuration, données, cache et dossiers d'exécution isolés dans `/tmp`.
- Un premier passage dans le bac à sable échouait sur les sockets localhost,
  quatre attentes de libellés Mac en français et une variable d'isolation qui
  masquait un scénario de test. Le passage corrigé a été effectué hors de cette
  restriction réseau, sans toucher à la configuration utilisateur.
- Les reproductions de cet audit utilisent du texte/audio synthétique, des
  enfants simulateurs, des erreurs injectées ou des API navigateur simulées.
  Aucun vrai micro ouvert, aucune insertion ou copie dans une application réelle,
  aucun modèle téléchargé, aucun changement de service.
- Le scénario matériel « veille → réveil → échec » n'a pas été reproduit ;
  aucun horaire précis d'un refus récent n'était disponible pour corrélation.
- Cet audit ne constitue pas une mesure de précision Whisper, un audit visuel
  rendu, un test matériel de tous les bureaux Linux ni une certification
  exhaustive de sécurité. La suite verte ne couvre pas les nouveaux scénarios.

Les scripts de reproduction sont conservés dans
[`archives/audit-linux-2026-09-19/`](archives/audit-linux-2026-09-19/README.md).
Les journaux personnels et les captures réelles n'y sont pas copiés.

## 7. Ordre de travail proposé

1. **Rendre le prochain incident observable** : erreur ALSA réelle, horodatage,
   code de sortie, identité de la capture ; traiter le journal du raccourci
   qui conserve du texte. Aucun changement audio global à l'aveugle.
2. **Garantir le cycle de vie du micro** : nettoyage après démarrage raté,
   prise exclusive à l'arrêt, arrêt explicite à la fermeture, verrou d'ouverture
   dans le navigateur, états fidèles.
3. **Garantir la récupération de la dictée** : conserver les échecs de façon
   privée et bornée, rendre le brut disponible, corriger les remplacements.
4. **Durcir le serveur et les écritures** : validation des hôtes, libération du
   verrou, configuration atomique, historique coordonné.
5. **Refermer les trous de parcours** : actualisation de l'historique, effacement,
   réglages immédiats et ponctuation française.

La décision de produit principale pour les correctifs est la durée et la forme
de conservation d'une dictée ratée. Proposition à valider lors de l'implémentation :
dans le dossier privé de session, avec expiration explicite, récupération ou
suppression par l'utilisateur. Pas de conservation permanente silencieuse.

Les correctifs doivent être préparés à partir de la **version Linux réellement
installée**, puis testés avant toute mise à jour de `~/murmur`. La branche Mac
actuelle et les deux fichiers de travail préexistants doivent rester préservés.
