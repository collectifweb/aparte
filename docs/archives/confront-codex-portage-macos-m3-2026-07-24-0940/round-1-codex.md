# Round 1 - Analyse Codex du plan M3

## Recommandation centrale

Je recommande **Option B** : desactiver sur Darwin les trois routes systeme
`POST /api/paste`, `POST /api/copy` et `POST /api/update/apply` des M3.

C'est plus large que l'insertion stricte, mais ce n'est pas de la
sur-ingenierie : le plan global a deja acte une regle generale, pas seulement
une regle "pas d'Accessibilite via HTTP". La formulation est explicite :
**aucune route HTTP ne realise une action a effet systeme ou privilegiee sur
Darwin** (`docs/plan-portage-macos.md:181-187`), et la table liste les trois
routes a desactiver (`docs/plan-portage-macos.md:196-198`).

Option A est trop etroite. Elle reduit le probleme a TCC/Accessibilite, alors
que le serveur resident macOS est aussi une surface capable de modifier le
presse-papiers systeme et de lancer une mise a jour `git`/`pip` + redemarrage.
`/api/update/apply` est meme une route a effet systeme plus lourde que
`/api/paste` : elle execute `apply_update()` puis peut appeler `restart()`
(`src/aparte/desktop.py:310-311`, `_handle_update_apply`). Le fait que le lot
fonctionnel "update macOS" soit M7 ne justifie pas de laisser une route deja
identifiee comme interdite active entre M3 et M7.

Le bon compromis "simple d'abord, chirurgical" est donc : ajouter un garde-fou
Darwin minimal dans `desktop.py`, couvrir les trois routes par tests mockes,
et ne pas implementer le tray/update macOS avant leur lot. Desactiver n'est pas
implementer M7.

## 1. Ce que j'approuve

Le decoupage `macos_insert.py` est sain. Un module natif neuf, importe seulement
depuis la branche Darwin de `clipboard.paste_text`, respecte le style deja pose
par `macos_permissions.py` et evite de charger PyObjC sur Linux. C'est le bon
niveau d'isolation : pas de grande abstraction de plateforme, pas de perturbation
du chemin Linux.

Le choix `pbcopy` puis Cmd+V est le bon chemin principal. Le code Linux existant
copie deja avant d'inserer (`src/aparte/clipboard.py:43-45`) pour garantir un
filet de securite ; reprendre cette semantique sur Mac garde le texte recuperable
si l'evenement clavier ne produit pas l'effet attendu.

Les invariants de `dictate_once()` et `toggle_dictation()` sont correctement
identifies pour le chemin principal : sortie vide avant copie/insertion
(`src/aparte/cli.py:277-287`, `src/aparte/cli.py:355-360`), historique avant
insertion, notification de succes apres `_deliver()` (`src/aparte/cli.py:301-313`).
Le plan a raison de s'appuyer dessus au lieu de recreer une orchestration Mac.

Le gate explicite `accessibility_trusted()` avant les CGEvent est indispensable.
Sans ca, macOS peut ignorer les evenements synthetiques sans fournir d'erreur
Python observable, et Aparté annoncerait un succes mensonger. C'est un point
critique, pas une coquetterie.

Le rejet de `osascript/System Events keystroke` reste correct. Pour une app
francaise, les guillemets, apostrophes typographiques et espaces insécables ne
sont pas des cas exotiques ; une solution qui les degrade ne doit pas devenir
le chemin principal.

Aucun changement de packaging n'est necessaire pour M3 : l'extra `[macos]`
contient deja `pyobjc-framework-Quartz` et `pyobjc-framework-ApplicationServices`,
gates sur Darwin (`pyproject.toml:52-56`). Le plan a raison de ne pas elargir ce
front.

## 2. Ce que je desapprouve

Je desapprouve la recommandation Option A. Elle est incoherente avec le plan
global et avec la nature reelle des routes. `/api/copy` n'exige pas TCC, mais
elle modifie le presse-papiers systeme via `pbcopy` (`src/aparte/clipboard.py:14-18`).
`/api/update/apply` n'exige pas TCC non plus, mais elle lance une mutation du
checkout/de l'installation et un redemarrage. Ce sont des effets systeme. Le
critere technique ne doit pas etre "permission TCC", il doit etre "effet systeme
declenche par HTTP".

Je desapprouve aussi l'argument "concern de M7" pour repousser
`/api/update/apply`. Justement parce que l'update macOS fiable est M7, la route
HTTP existante ne doit pas rester le chemin par defaut en attendant. La desactiver
maintenant evite une surface connue sans implementer le remplacement.

Le plan surestime la garantie "jamais de no-op silencieux" dans `macos_insert`.
On peut lever si Quartz est absent, si `CGEventCreateKeyboardEvent` retourne
`None`, ou si l'Accessibilite est refusee avant de poster. En revanche, il ne
faut pas promettre de detecter un "echec de post" comme si `CGEventPost` donnait
un statut fiable. Le test mocke doit verrouiller notre contrat observable, pas
inventer une observabilite que macOS ne fournit pas.

L'affirmation "les appelants CLI `aparte dictate`, `aparte toggle` sont vivants
sur Mac des M3" est trop large. `dictate` peut devenir vivant avec les branches
audio/copie/insertion, mais `toggle` appelle encore `session.py`, qui depend de
`arecord` et de `/proc/<pid>/cmdline` (`src/aparte/session.py:80-92`,
`src/aparte/session.py:184-193`). Le plan global dit au contraire que la bascule
macOS a lieu via `RecordingController` resident, sans `session.py`
(`docs/plan-portage-macos.md:72-86`, `docs/plan-portage-macos.md:207-213`).
M3 ne doit donc pas vendre `aparte toggle` comme fonctionnel sur Mac.

La phrase "les invariants sont deja dans du code partage" doit etre limitee aux
chemins `dictate_once()` et `toggle_dictation()`. `handle_output()` pour
`aparte transcribe --paste` ou `aparte record --paste` appelle `paste_text()`
directement, sans historique ni notification d'echec (`src/aparte/cli.py:367-372`).
Ce n'est pas forcement un bug M3, mais ce n'est pas le meme contrat produit.

## 3. Ce qui manque

Il manque des tests Darwin pour **les trois** routes systeme : `POST /api/paste`,
`POST /api/copy`, `POST /api/update/apply` doivent rendre 404 sur Darwin, et les
memes routes doivent rester inchangees sur Linux. Aujourd'hui les trois routes
sont actives dans `desktop.py` (`src/aparte/desktop.py:294-311`). Les tests
doivent patcher la detection de plateforme et verifier le comportement avec une
requete acceptee par l'Origin check, sinon on teste seulement le garde-fou
Origin existant.

Il manque une verification du cout UI de l'Option B. Le JavaScript appelle encore
`/api/copy` avant de tomber sur `navigator.clipboard.writeText`
(`src/aparte/assets/app.js:279-287`, `src/aparte/assets/app.js:644-652`). Ce repli
rend Option B acceptable, mais il faut au moins le nommer et, idealement, tester
ou ajuster le flux pour ne pas casser le bouton Copier sur Mac. Pour
`/api/update/apply`, le panneau peut encore afficher un bouton qui appellera une
route desactivee (`src/aparte/assets/app.js:700-728`) ; ce n'est pas un blocage
backend, mais c'est un risque UX a ne pas masquer.

Il manque la distinction entre `accessibility_trusted() is False` et
`accessibility_trusted() is None`. `False` veut dire "permission connue et refusee" :
on peut guider l'utilisateur vers les Reglages. `None` veut dire API/framework
injoignable : le bon message est plutot packaging/environnement (`.[macos]`,
PyObjC, execution hors Mac). Ouvrir les Reglages dans le cas `None` serait du bruit.

Il manque un garde anti-spam pour le parcours guide Accessibilite. Prompt + ouverture
des Reglages a chaque echec est trop agressif si l'utilisateur refuse volontairement.
Un boolen "deja tente dans ce processus" suffit ; pas besoin de persistance.

Il manque un contrat clair sur les exceptions natives. `paste_text()` devrait remonter
un `ClipboardError` comprehensible pour les echecs de copie, d'Accessibilite ou de
Quartz, parce que `_deliver()` affiche directement `str(exc)` dans la notification
(`src/aparte/cli.py:306-310`). Des `ImportError`, `AttributeError` ou exceptions PyObjC
brutes produiraient une experience mediocre.

Il manque des tests specifiques pour le mode `direct` avec texte francais long et
caracteres critiques (`’`, `« »`, espace insecable). Les tests mockes ne prouvent
pas l'effet OS, mais ils doivent au moins prouver que la fonction conserve la chaine
et la decoupe de facon controlee si le plan parle de "blocs".

## 4. Ce que je remettrais en question

Je remettrais en question le statut de `terminal` sur Mac. Le plan propose de le
collapser vers Cmd+V, sauf `direct`. C'est probablement acceptable, mais il faut
l'assumer comme une divergence de configuration : un utilisateur qui partage un
`config.json` Linux avec `paste_mode="terminal"` n'obtient pas une frappe Unicode
Mac, il obtient un collage standard.

Je remettrais en question `kCGHIDEventTap` comme choix categorique. Sans Mac reel,
on ne peut pas trancher proprement entre `kCGHIDEventTap` et `kCGSessionEventTap`,
ni la necessite d'un tres court delai entre keydown et keyup. Le plan fait bien
de l'identifier comme point sensible ; je ne bloquerais pas M3 dessus, mais je ne
survendrais pas la certitude.

Je remettrais en question le code retour 404 comme decision absolue. 404 est
coherent avec "route indisponible sur Darwin" et limite l'exposition de surface ;
405/501 serait plus explicite pour un client. Comme le plan global dit 404, je
garderais 404 pour ne pas rouvrir inutilement le consensus.

Je remettrais en question le moment exact du garde Darwin dans `do_POST`. L'Origin
check actuel accepte les requetes sans `Origin` pour les clients CLI
(`tests/test_desktop.py`, `OriginCheckTest.test_a_request_without_origin_is_accepted`).
Le garde Darwin doit donc etre un garde route, pas seulement une confiance dans
l'Origin check. Le comportement 403 pour origine etrangere puis 404 pour route
Darwin interdite avec origine valide est acceptable, mais il doit etre deliberé.

Je remettrais enfin en question l'absence totale de modification UI en M3. Je
comprends la contrainte chirurgicale et je ne demande pas un redesign. Mais si
on desactive `/api/paste` et `/api/update/apply` sur Mac, l'interface web garde
des boutons qui ne peuvent plus reussir. C'est tolerable pour un lot backend
mocke, pas pour une smoke suite Mac M8. Au minimum, il faut noter ce reliquat
dans le plan M3 ou le backlog immediat.
