# Round 1 - Analyse critique du plan Claude

## 1. Ce que j'approuve

### Le recentrage du diagnostic est juste

Je valide la requalification : l'incompatibilite `hotwords` / `faster-whisper`
n'explique pas la panne locale si la machine avait bien `faster-whisper 1.2.1`.
Le code passe effectivement `hotwords` a `WhisperModel.transcribe()` dans
`src/aparte/transcription.py:128-130`, et `pyproject.toml` autorise encore
`faster-whisper>=1.0`. La dette d'empaquetage reste donc reelle : la release
[`faster-whisper 1.0.2`](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.0.2)
annonce l'ajout de `hotwords`, donc `>=1.0.2` est le bon plancher minimal pour
ce code.

### Les causes prouvees P1/P2 sont solides

Le bug "rien ne sort" est bien aggrave par deux comportements certains :

- `dictate_once()` et `toggle_dictation()` appellent `_notify_inserted(output,
  target)` avant `history.record()` puis `paste_text()` / `copy_text()`
  (`src/aparte/cli.py:283-289`, `src/aparte/cli.py:332-338`).
- `_notify_inserted()` signale "Rien a transcrire" sur `not output.strip()`,
  mais l'appelant continue ensuite vers `paste_text("")` ou `copy_text("")`
  (`src/aparte/cli.py:296-306`).
- `paste_text()` commence par `copy_text(text)` dans tous les modes
  (`src/aparte/clipboard.py:39`), donc une transcription vide remplace bien le
  presse-papiers par le vide.

Le correctif A ("sortir avant insertion si vide") et le correctif B ("notifier
le succes apres l'action, rendre l'echec visible") sont donc directement
alignes sur le symptome utilisateur.

### Historique avant insertion : bon choix

Enregistrer l'historique avant l'insertion est le bon ordre. Si `xdotool`,
`xclip` ou le focus X11 echoue, le texte reste recuperable. C'est important
parce que `history.record()` est volontairement non bloquant et silencieux, et
parce que `main()` ne fait actuellement qu'ecrire `error: ...` sur `stderr`,
sortie invisible depuis un raccourci Cinnamon.

### La langue par defaut a `fr` est coherente avec le produit

Le projet est clairement pense "francais d'abord" : UI francaise, post-traitement
typographique francais, `CLAUDE.md` qui documente deja le piege de la detection
automatique sur audio pauvre. Changer `DEFAULT_CONFIG["language"]` de `None` a
`"fr"` est une correction de produit, pas seulement une preference.

Claude a aussi raison de dire que cela ne corrige pas le poste existant si son
fichier contient explicitement `"language": null`, car `load_config()` applique
les valeurs du fichier par-dessus `DEFAULT_CONFIG` (`src/aparte/config.py:171-172`).

### R1 est globalement corrige

La retractation sur le cache est justifiee. `_handle_save_config()` appelle bien
`transcriber_cache.clear()` apres une sauvegarde depuis l'interface
(`src/aparte/desktop.py:420-421`), donc "changer la langue dans Reglages ne prend
effet qu'apres redemarrage" etait faux.

Le defaut restant est bien plus etroit : `get_transcriber()` recharge la config a
chaque requete, mais le cache est indexe seulement par `model`
(`src/aparte/desktop.py:199-213`). Une edition directe du fichier de config
pendant que le serveur tourne peut donc laisser un transcripteur construit avec
ancienne langue, anciens hotwords, ancien backend ou ancien device.

Je valide aussi l'idee de garder `transcriber_cache.clear()` meme avec une cle
complete : cela libere les gros modeles que l'utilisateur vient de rendre
inatteignables via l'UI.

## 2. Ce que je desapprouve

### C ne doit pas supprimer le WAV d'une session morte sans autre mecanisme

Le plan dit : ajouter `arecord -d <plafond>`, puis faire supprimer le `.wav` par
`get_active_session()` quand le processus est mort. En l'etat, c'est une perte
de donnees volontaire.

Avec `-d 300`, le scenario devient :

1. l'utilisateur depasse 5 minutes ;
2. `arecord` termine proprement et finalise le WAV ;
3. le prochain `toggle` appelle `get_active_session()` ;
4. `get_active_session()` voit le PID mort, supprime la session et, selon le
   plan, supprime aussi le WAV ;
5. rien ne transcrit jamais l'audio pourtant capture.

Ce n'est pas seulement un compromis "une dictee trop longue est perdue". C'est
une perte silencieuse d'un fichier valide au moment exact ou l'utilisateur
demande l'arret. Si on ajoute un plafond, il faut soit :

- conserver la session morte mais transcrivable quand le WAV existe et que
  `started_at + max_recording_seconds` est coherent ;
- ajouter un etat explicite "recording_completed" que le prochain toggle
  transcrit ;
- ou notifier clairement un timeout, ce qui exige un superviseur encore vivant,
  pas seulement un `arecord -d` lance par un CLI deja termine.

Supprimer les WAV orphelins reste souhaitable, mais pas dans une branche qui
melange "processus mort donc obsolete" et "processus mort parce qu'il a atteint
le plafond prevu".

### Le plafond a 300 s est trop tranche pour etre introduit comme defaut muet

Je ne rejette pas un plafond. Je rejette un plafond muet qui perd tout a 5
minutes. Cinq minutes est raisonnable pour limiter le degat d'un micro oublie,
mais pas raisonnable si le produit ne donne aucun retour et ne transcrit pas ce
qui a deja ete enregistre.

Si l'implementation ne sait pas recuperer l'audio au plafond, je prefererais un
plafond plus haut par defaut ou non expose comme garantie UX. Le bon objectif
n'est pas seulement "ne pas saturer le disque" ; c'est "ne pas transformer une
dictee longue en disparition silencieuse".

### Le plan sous-traite la vraie cause plausible du `arecord` de 31 minutes

Claude ecrit ne pas savoir pourquoi le premier `arecord` n'a pas ete arrete. On
ne peut pas le prouver avec les seuls fichiers, mais il y a une cause plausible
dans `session.py` et elle merite d'etre traitee, pas seulement bornee.

Le probleme n'est pas `killpg` en soi : avec `start_new_session=True`,
`Popen.pid` devient normalement le PGID, donc `os.killpg(session.pid, SIGINT)`
est le bon signal pour arreter `arecord` (`src/aparte/session.py:95-99`,
`src/aparte/session.py:126-139`).

Le probleme est l'absence totale d'atomicite et de verrou interprocessus autour
de `toggle-session.json` :

- `start_toggle_recording()` fait un check-then-act non atomique :
  `get_active_session()` puis `Popen()` puis `write_text()` (`src/aparte/session.py:75-118`).
- l'ecriture de session se fait directement dans le fichier final, sans fichier
  temporaire + `replace()`.
- `get_active_session()` supprime le fichier de session sur n'importe quelle
  exception de lecture/parsing (`src/aparte/session.py:58-68`).
- le tray appelle `get_active_session()` toutes les secondes
  (`src/aparte/tray.py:138-145`), et le doctor/status peuvent aussi le faire.

Donc un lecteur peut tomber sur un fichier partiellement ecrit ou un etat
transitoire, le supprimer, et laisser un `arecord` vivant sans session. Ensuite,
un nouveau `toggle` voit "pas de session" et demarre un second enregistrement au
lieu d'arreter le premier. Cela colle mieux au gros WAV abandonne qu'une simple
defaillance de `killpg`.

Autre race possible : deux invocations `toggle` demarrent presque en meme temps
quand aucune session n'existe ; les deux peuvent passer le premier
`get_active_session()`, lancer deux `arecord`, puis la derniere ecriture gagne.
Le processus perdant devient orphelin. Ce scenario demande une collision courte,
mais un raccourci global peut produire ce genre de chevauchement par double
pression ou repetition de touche.

Conclusion : le plafond `-d` est utile comme garde-fou, mais il ne remplace pas
un verrou de session et une ecriture atomique.

### Exemple R1 a corriger : `APARTE_*`

Je ne garderais pas `APARTE_*` comme exemple principal de transcripteur perime.
Un processus serveur deja lance ne voit pas les variables d'environnement
modifiees dans un shell externe. Et cote CLI, `transcribe_via_running_app()`
desactive justement la delegation quand certaines surcharges d'environnement
sont presentes (`src/aparte/desktop.py:112-118`).

Les bons exemples sont : edition manuelle de `~/.config/aparte/config.json`,
outil futur qui appelle `update_config()` hors serveur, synchronisation externe
du fichier de config. Ceux-la rendent vraiment `current_settings()` different
pendant que `transcriber_cache[model]` reste ancien.

## 3. Ce qui manque

### Un verrou interprocessus pour la session toggle

Il manque une mesure structurelle autour de `toggle-session.json`. Je mettrais
dans le plan :

- verrou fichier autour de `get_active_session()` / start / stop ;
- ecriture atomique du JSON (`tmp` dans le meme repertoire puis `replace`) ;
- ne pas supprimer le fichier de session sur erreur JSON sans quarantaine ou
  relecture courte, car une erreur peut venir d'une ecriture concurrente ;
- test de double demarrage concurrent : un seul `Popen()` doit gagner.

Sans cela, le plan borne les consequences mais laisse une source plausible
d'orphelins.

### Un etat "processus mort mais audio transcrivable"

Si `arecord -d` est retenu, `get_active_session()` ne peut plus reduire
"processus mort" a "session stale". Il faut distinguer :

- PID mort + WAV absent : stale, nettoyer ;
- PID mort + WAV present + duree/age compatible avec le plafond : arret
  automatique, a transcrire au prochain toggle ;
- PID mort + WAV tres ancien : orphelin, nettoyer selon politique explicite.

Le test "session morte -> `.wav` supprime" propose par Claude est donc
incomplet ; il faut aussi le test inverse "session morte par plafond -> `.wav`
transcrit".

### L'UI du nouveau reglage

Le plan dit d'ajouter `max_recording_seconds` a `DEFAULT_CONFIG`, `Settings` et
`EDITABLE_FIELDS`. Si ce reglage est vraiment editable depuis Settings, il manque
les assets :

- `src/aparte/assets/index.html` : controle dans le panneau ;
- `src/aparte/assets/app.js` : chargement et sauvegarde ;
- `src/aparte/assets/i18n.js` : libelles FR/EN.

Aujourd'hui `app.js` liste explicitement chaque champ charge et poste
(`src/aparte/assets/app.js:400-422`, `src/aparte/assets/app.js:477-496`). Ajouter
seulement `EDITABLE_FIELDS` expose la valeur dans `/api/config`, mais ne cree
aucun controle.

Si le reglage n'est pas destine a l'UI, il ne devrait pas etre dans
`EDITABLE_FIELDS`; il devrait rester config fichier / environnement, avec docs.

### Validation de configuration pour `max_recording_seconds`

Il faut definir la semantique des valeurs :

- `0` signifie-t-il "pas de plafond" ou faut-il l'interdire ?
- minimum durci a 1 s, comme `audio._record_wav_arecord()` le fait avec
  `math.ceil()` et `max(1, ...)` ?
- maximum raisonnable pour eviter une valeur accidentelle enorme ?
- type float ou int ?

Le plan mentionne `positive_int`, mais il faut expliciter la politique, surtout
si le reglage arrive dans l'UI.

### Tests d'insertion : il faut verifier "pas d'appel", pas seulement clipboard intact

Pour A/B, les tests doivent mocker `paste_text`, `copy_text`, `notify` et
`history.record` afin de prouver :

- sortie vide : aucune insertion/copie appelee ;
- sortie vide : notification "Rien a transcrire" appelee ;
- sortie non vide : succes notifie apres l'appel effectif ;
- echec insertion : historique tente avant l'insertion, notification critique
  emise, exception propagee.

Tester seulement l'etat du presse-papiers serait trop indirect et dependant des
outils systeme.

### Le chemin `last` garde un risque voisin

`aparte last --target paste` appelle directement `paste_text(text)` sans
notification d'echec visible (`src/aparte/cli.py:57-69`). Ce n'est pas la panne
initiale, et `last` ne manipule pas une sortie vide si `history.last()` renvoie
quelque chose, mais le probleme "stderr invisible depuis raccourci" existe aussi
si l'utilisateur lie `last` a une touche ou l'utilise comme recuperation. Je ne
le mettrais pas forcement dans le patch principal, mais il faut le noter.

## 4. Ce que je remettrais en question

### `.strip()` suffit-il pour "rien a inserer" ?

Pour le bug actuel, oui : `.strip()` est le bon seuil minimal. Il couvre `""`,
espaces, tabs, retours ligne et espaces insecables, et il est coherent avec
`history.record()` qui ignore deja `not text.strip()` (`src/aparte/history.py:54-56`).

Mais il ne faut pas vendre cela comme detection generale de "rien d'utile".
Python ne retire pas certains caracteres invisibles comme `U+200B` ou `U+FEFF`.
Et une sortie composee uniquement de ponctuation, de symboles ou de caracteres
hors alphabet peut etre soit une hallucination, soit une dictee legitime
("point", "slash", ponctuation, etc.).

Je garderais donc `.strip()` pour "vide structurel", sans ajouter de filtre
semantique agressif. Si on veut durcir les invisibles, il faut un helper nomme
explicitement, par exemple `has_insertable_text()`, qui retire seulement les
categories Unicode de format/controle en plus des espaces. Je n'integrerais pas
un detecteur de charabia dans ce correctif.

### Le texte de notification d'echec

"Le texte est dans l'historique et recuperable par `aparte last`" est une bonne
idee, mais techniquement `history.record()` peut echouer silencieusement par
design. La probabilite est faible, mais la formulation la plus exacte serait
conditionnelle ou plus prudente, par exemple "Aparté a tenté de le garder dans
l'historique ; essaie `aparte last`".

Cela dit, je comprends le choix produit : dans la plupart des cas, l'historique
sera bien ecrit, et le message doit etre actionnable.

### La cle de cache complete

La cle proposee `(transcriber, model, language, device, compute_type,
whisper_cpp, hotwords)` est la bonne direction. Je la garderais comme tuple
hashable, avec `hotwords` deja normalise en tuple dans `Settings`.

Je questionne seulement deux details :

- si `backend="auto"` tombe d'abord sur faster-whisper puis fallback CPU apres
  erreur CUDA, la cle reste celle de la config initiale ; c'est acceptable, mais
  il faut le savoir ;
- `whisper_cpp` ne sert que pour le backend `whisper.cpp` ou le fallback `auto`,
  donc l'inclure partout est un peu large mais preferable a une cle trop
  intelligente.

### Le default `language="fr"` et les utilisateurs non francophones

Je l'approuve pour ce produit, mais c'est une decision produit, pas un fait
technique. Si Aparté veut rester bilingue FR/EN a moyen terme, il faudra
eventuellement baser le defaut sur la locale ou rendre le choix plus visible au
premier lancement. Pour ce bug precis, le defaut francais est le bon correctif.

### Changelog / CLAUDE / README

Mettre a jour la doc est utile, mais attention a ne pas documenter comme
invariant une solution encore debattue (`-d 300` avec perte silencieuse). Les
docs doivent suivre l'implementation finale, surtout sur la garantie utilisateur
en cas de plafond.
