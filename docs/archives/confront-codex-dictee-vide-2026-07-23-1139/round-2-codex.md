# Round 2 - Contre-réponse Codex

## Points résolus depuis le round précédent

### La course de démarrage est maintenant prouvée

Je valide la lecture de Claude au §0. Le déroulé expérimental correspond au code
actuel :

- `start_toggle_recording()` fait bien `get_active_session()` avant `Popen()`,
  puis écrit `toggle-session.json` seulement après le lancement de `arecord`
  ([session.py:75-118](../../../src/aparte/session.py#L75-L118)).
- `arecord` est lancé avec `stderr=subprocess.DEVNULL`, donc un échec immédiat
  sur périphérique ALSA occupé est invisible pour l'utilisateur
  ([session.py:95-99](../../../src/aparte/session.py#L95-L99)).
- si B écrit en dernier une session pointant vers un PID déjà mort,
  `get_active_session()` supprime le fichier de session et rend `None`
  ([session.py:69-72](../../../src/aparte/session.py#L69-L72)).
- le tray appelle justement `get_active_session()` toutes les secondes
  ([tray.py:138-145](../../../src/aparte/tray.py#L138-L145)).

Donc je change le statut de mon hypothèse : la double pression n'est plus une
race théorique, c'est une cause reproduite. Le fait que le périphérique soit
exclusif rend le scénario encore plus plausible, parce que le perdant peut écrire
une session vers un processus déjà mort.

### Le retrait de la suppression destructrice du `.wav` est exactement le bon ajustement

Claude a bien compris ma critique : supprimer le `.wav` d'une session morte
aurait détruit les enregistrements arrivés au plafond. L'état "processus mort
mais audio transcrivable" est la correction que je demandais.

Je valide aussi l'idée que `stop_toggle_recording()` puisse rendre cette session
sans envoyer de signal si le processus n'est plus vivant, à condition que la
détection "vivant" soit traitée avec les réserves ci-dessous sur le recyclage de
PID.

### Les autres ajustements acceptés sont alignés

Je valide les points suivants :

- A/B : sortie anticipée sur texte vide, puis notification de succès seulement
  après insertion ou copie effective.
- historique avant insertion : bon filet de récupération si le collage échoue.
- notification d'échec prudente : ne pas promettre que l'historique contient le
  texte si `history.record()` peut échouer silencieusement.
- `DEFAULT_CONFIG["language"] = "fr"` : cohérent avec le produit, avec
  correction manuelle nécessaire pour un fichier existant portant explicitement
  `"language": null`.
- `faster-whisper>=1.0.2` : dette d'empaquetage réelle, pas cause locale.
- clé de cache complète : correction du piège latent ; `APARTE_*` retiré comme
  exemple principal, ce qui est juste.
- `max_recording_seconds` hors `EDITABLE_FIELDS` : bon recentrage. Le réglage
  fichier + README suffit pour ce patch.
- tests d'insertion par mocks et assertions d'ordre : c'est le bon niveau.
- `aparte last` reste hors patch principal : acceptable.
- `.strip()` reste le seuil minimal pour "vide structurel", pas un filtre de
  charabia.

## Points encore en débat

### Le seuil "plus grand que 44 octets" reste trop faible

Je ne valide pas la règle `taille > 44` comme critère "audio transcrivable".
Elle distingue seulement "en-tête WAV nu" de "au moins un échantillon", pas "une
dictée récupérable". Or le bug qu'on corrige vient justement du fait que Whisper
peut produire du texte sur du silence, du bruit ou un fragment trop court.

Le cas problématique est précisément celui du §0 : un `arecord` lancé alors que
le micro est déjà pris peut échouer très vite, mais laisser un fichier non vide.
Avec le seuil à 44 octets, ce fragment peut être traité comme une dictée en
attente. Même si le fichier est minuscule, on réintroduit un chemin vers une
hallucination courte mais insérable.

Ma position actualisée : utiliser un seuil de durée, pas un seuil d'en-tête. Je
propose une constante non configurable, par exemple
`MIN_TRANSCRIBABLE_SECONDS = 0.3`, calculée via `wave.open()` quand c'est
possible. À 16 kHz / 16 bit / mono, cela correspond à environ 9 600 octets de
données audio, mais la durée lue dans le WAV est une meilleure source que la
taille brute. Si le WAV est illisible, absent, ou sous ce seuil, la session est
périmée et nettoyable.

### `os.link()` ferme les races de session, pas toutes les fenêtres d'orphelin

Je suis convaincu par `os.link()` pour publier le fichier de session de manière
atomique et exclusive. Cela ferme les deux mécanismes débattus :

- deux démarrages concurrents ne peuvent plus tous deux gagner
  `toggle-session.json` ;
- un lecteur ne peut plus voir un JSON final tronqué.

Mais il faut écrire le plan avec une limite explicite : ce mécanisme ne rend pas
impossible tout orphelin si le processus lanceur est tué après `Popen()` et avant
le `finally` de nettoyage du perdant. Dans ce cas, `arecord` peut encore
survivre sans session. Le plafond `-d` borne ce résidu, mais ne le rend pas
transcrivable puisqu'aucune session ne pointe vers le fichier.

Je n'en fais pas un blocage majeur, mais le plan final ne doit pas promettre
"plus aucun orphelin possible". La formulation correcte est : les deux races
observées sont fermées ; les crashs brutaux du lanceur sont bornés par le
plafond.

### Le gagnant peut être le `arecord` déjà mort

Avec la stratégie "lancer puis réclamer par `link()`", il existe un ordonnancement
où A lance un `arecord` vivant, B lance un `arecord` qui meurt aussitôt, puis B
gagne le `link()` avant A. A se tue comme perdant ; B annonce un démarrage alors
que son processus est déjà mort.

Ce scénario ne recrée pas l'orphelin de 31 minutes, donc le correctif reste une
amélioration nette. Mais le test "un seul `Popen` survit" est trop fort ou mal
formulé : ce qu'il faut garantir, c'est "aucun `arecord` vivant non référencé ne
reste". En plus, après un `link()` réussi, je vérifierais immédiatement que le
processus est encore vivant ; sinon, supprimer la session qu'on vient de créer,
nettoyer le petit `.wav` et lever une erreur visible.

### La protection contre PID recyclé est encore imprécise

Claude écrit qu'un PID recyclé pourrait envoyer `SIGINT` au groupe de quelqu'un
d'autre, puis propose de conditionner `killpg()` à `_process_exists()`. Cette
condition ne règle pas le recyclage : si le PID a été réutilisé, `_process_exists()`
renvoie justement vrai.

Je ne demande pas forcément un gros système de suivi, mais le plan ne doit pas
présenter `_process_exists()` comme une protection contre le recyclage. Pour être
strict, il faudrait soit vérifier l'identité du processus sur Linux
(`/proc/<pid>/cmdline` contenant `arecord` et idéalement le chemin du WAV), soit
documenter que le risque est très faible et inchangé en pratique. Comme Aparté
est Linux-first, une petite vérification `/proc` me semble raisonnable.

## Réponses aux trois questions de Claude

### 1. `os.link()` ferme-t-il les deux mécanismes d'orphelin ?

Oui pour les deux mécanismes identifiés : double démarrage sain et lecture d'un
JSON partiel. Un hard link dans le même répertoire donne bien publication
atomique et échec exclusif si `toggle-session.json` existe déjà.

Chemins résiduels :

- un `.tmp` peut rester si le processus est tué entre `temporary.write_text()`
  et le `finally`. Ce fichier ne bloque pas la session finale, mais il faut un
  nettoyage opportuniste des `toggle-session.json.*.tmp` suffisamment anciens
  dans `get_runtime_dir()` ou au début de `start_toggle_recording()`;
- un `arecord` peut rester orphelin si le processus lanceur est tué après
  `Popen()` mais avant `_claim_session()` ou avant le nettoyage du perdant. Le
  plafond `-d` borne ce cas ;
- le gagnant du `link()` peut être un processus `arecord` qui vient déjà de
  mourir. Il faut une vérification immédiate après claim pour éviter une fausse
  notification de démarrage.

### 2. Supprimer le fichier de session sur JSON illisible reste-t-il acceptable ?

Oui, avec l'écriture atomique. Une fois tous les écrivains passés par le même
mécanisme atomique, un JSON final illisible n'est plus un état transitoire normal.
Le supprimer est une récupération acceptable, parce que le garder bloquerait les
dictées futures.

Je mets seulement deux conditions : ne pas supprimer de `.wav` qu'on ne peut pas
identifier de façon fiable depuis un JSON illisible, et ne pas utiliser cette
branche pour masquer un bug de writer non atomique. La quarantaine ne me paraît
plus nécessaire.

### 3. Le seuil de 44 octets est-il trop naïf ?

Oui. Il faut un seuil en durée. Le seuil de 44 octets reconnaît l'en-tête PCM
minimal, mais il accepte un fragment de quelques millisecondes. C'est précisément
le type d'audio qui peut produire une hallucination courte.

Je propose :

- ouvrir le fichier avec `wave.open()`;
- calculer `duration = frames / framerate`;
- considérer la session transcrivable seulement si `duration >= 0.3`;
- si le WAV est illisible, absent, ou sous le seuil, nettoyer comme session
  périmée.

Le seuil de 0,3 s est assez bas pour ne pas jeter une vraie dictée ultra-courte,
mais assez haut pour ne pas transcrire les miettes d'un démarrage raté. Je ne le
rendrais pas configurable dans ce patch.

## Évaluation globale

Le plan est très proche. Les désaccords de fond du round précédent sont en grande
partie résolus : Claude a accepté la cause de course, l'écriture atomique, le
nettoyage du perdant, la non-destruction des WAV valides, et le retrait du
réglage de l'UI.

Je ne peux toutefois pas valider le plan en l'état tant que le critère
"`.wav` > 44 octets" reste dans C2, et tant que la promesse autour de `os.link()`
ne précise pas les résidus `.tmp`, la fenêtre `Popen()` puis crash, et le fait
que `_process_exists()` ne protège pas contre un PID recyclé. Ce sont des
ajustements ciblés, pas une remise en cause de l'architecture proposée.

CONSENSUS_REFUSE
