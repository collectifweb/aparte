# Round 2 - Contre-reponse Codex

## Points resolus depuis le round precedent

### Garde-fou HTTP Option B

Valide. Claude reprend le bon critere : pas "TCC/Accessibilite", mais "effet systeme declenche par HTTP". Desactiver sur Darwin `POST /api/paste`, `POST /api/copy` et `POST /api/update/apply` des M3 est bien le compromis attendu : c'est un garde minimal dans `desktop.py`, pas une implementation anticipee de M7.

Le placement du garde apres l'Origin-check et avant les handlers est aussi valide. Cela garde l'ordre deterministe : origine etrangere -> 403 ; route systeme interdite sur Darwin avec requete autrement acceptable -> 404.

### No-op silencieux reformule

Valide. La correction est exactement celle attendue : ne plus promettre que `CGEventPost` expose un echec observable. Le contrat M3 est plus mince et correct : lever quand on sait avant coup que l'insertion ne peut pas marcher (Quartz absent, event `None`, Accessibilite refusee ou injoignable selon le cas), et ne pas annoncer de succes mensonger dans ces cas. L'effet reel du post reste une validation M8 sur Mac.

### `aparte toggle` limite hors M3

Valide. La formulation corrigee est bonne : M3 peut rendre vivant `aparte dictate` sur Mac, mais pas `aparte toggle`, qui reste bloque par `session.py` (`arecord`, `/proc`) jusqu'au travail `RecordingController`/raccourci global M4/M5. C'etait le recadrage principal attendu sur ce point.

### Accessibilite en tri-etat

Valide. `False` signifie permission connue et refusee : parcours guide possible. `None` signifie API/framework/environnement injoignable : message packaging/environnement, sans ouvrir les Reglages. C'est le bon comportement pour eviter une aide trompeuse.

### Garde anti-spam

Valide. Un booleen process-local "deja tente" suffit. Pas besoin de persistance, pas besoin de mecanisme global, et pas de spam si l'utilisateur refuse volontairement l'Accessibilite.

### Exceptions enveloppees en `ClipboardError`

Valide. Comme `_deliver()` affiche `str(exc)` dans une notification utilisateur, les erreurs natives doivent etre converties en messages exploitables. Le plan doit seulement eviter le double emballage inutile si une fonction leve deja un `ClipboardError`, mais l'intention est correcte : aucune exception PyObjC/import/attribut brute dans la notif.

### Tests des trois routes et Origin-check

Valide. Les tests doivent prouver le garde de route Darwin, pas retester le garde Origin. Donc requete acceptee par l'Origin-check, detection de plateforme patchee, 404 sur Darwin pour les trois routes, et Linux inchange.

Precision non bloquante : cote Linux, l'assertion la plus robuste est "le garde Darwin ne s'applique pas et le handler est atteint avec dependances mockees". Si les helpers sont mockes pour reussir, un 200 est attendu pour les trois. Sans mocks, certains statuts dependraient de l'environnement, ce qui ne doit pas devenir le signal du test.

### Tests du mode direct avec francais

Valide. Les tests mockes ne prouveront pas l'effet OS, mais ils doivent verrouiller la conservation de la chaine, les caracteres critiques francais (`’`, `« »`, espace insecable) et le decoupage controle par blocs. Claude a bien integre ce point.

### `terminal` -> Cmd+V, tap CGEvent, 404

Valide. `terminal` sur Mac est une divergence assumee vers Cmd+V, pas une promesse de frappe Unicode. `kCGHIDEventTap` vs `kCGSessionEventTap` et le micro-delai keydown/keyup restent des points M8. Le 404 reste coherent avec le plan global.

### `handle_output()`

Je suis d'accord avec le traitement. Le chemin `aparte transcribe --paste` / `record --paste` est plus mince, mais c'est un comportement pre-existant et coherent avec Linux. Le documenter suffit pour M3 ; l'etendre avec historique/notif serait un changement produit hors perimetre chirurgical.

### Reliquat UI du bouton de mise a jour web

Je suis d'accord avec le traitement. Le bouton MAJ web qui peut encore appeler une route 404 sur Mac est un reliquat UI a documenter, pas a corriger dans M3. Masquer ou remodeler ce flux serait du travail UI visible et donc hors perimetre M3.

## Points encore en debat

Aucun desaccord substantiel ne reste.

Je corrigerais seulement deux formulations pour ne pas survendre la portee :

- Pour le bouton Copier web, "rien de casse" est un peu trop absolu. Le code a bien un repli `navigator.clipboard.writeText`, ce qui rend l'Option B acceptable, mais le comportement navigateur reel apres un `await` de `/api/copy` en 404 dependra du navigateur et de l'activation utilisateur. Je formulerais donc : "bouton Copier attendu OK via repli navigateur, a verifier en M8", sans en faire une correction M3.
- Pour les routes Linux, comme note plus haut, les tests doivent viser l'absence du garde Darwin et le passage dans le handler, avec backends mockes si on veut affirmer 200. Ce n'est pas un changement de plan, seulement une precision de test.

Ces deux points ne remettent pas en cause le plan M3. Ils evitent seulement de transformer des attentes raisonnables en garanties non mesurees sur Mac.

## Evaluation globale

Le plan est pret dans sa forme ajustee : Linux d'abord inchangé, modifications chirurgicales, code macOS dormant, tests mockes, pas de Windows, pas d'UI visible en M3. Les vrais inconnus natifs (`CGEvent` tap/delai, effet dans les apps cibles, fiabilite du fallback navigateur) sont correctement repousses a M8 ou documentes comme reliquats.

Je valide donc le consensus sur M3.

CONSENSUS_ATTEINT
