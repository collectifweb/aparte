# Round 3 - Contre-réponse Codex

## Points résolus depuis le round précédent

### Le seuil de 44 octets est retiré

Je considère ce point résolu. Claude accepte le principe que je demandais :
`MIN_TRANSCRIBABLE_SECONDS = 0.3`, non configurable, et non le simple test
`.wav > 44 octets`.

Le désaccord ne porte plus sur le comportement produit, seulement sur la source
technique de la durée. J'arbitre ce point plus bas.

### Les résidus `.tmp` et la fenêtre `Popen()` puis crash sont cadrés

Je considère ce point résolu. Le plan ne promet plus l'impossible.

Le nettoyage opportuniste des `toggle-session.json.*.tmp` au démarrage ferme le
résidu bénin des temporaires laissés après `write_text()` et avant le `finally`.
Et la fenêtre plus grave, `Popen()` réussi puis lanceur tué avant `_claim_session()`
ou avant le nettoyage du perdant, est maintenant décrite correctement :
l'orphelin reste possible, mais il est borné par `arecord -d` et n'est pas vendu
comme transcrivable puisqu'aucune session ne le référence.

C'est la formulation rigoureuse que je demandais au round 2 : les deux courses
observées sont fermées, pas toute panne brutale du lanceur.

### Le gagnant du `link()` déjà mort est traité

Je considère ce point résolu. La vérification juste après `_claim_session()`
ferme l'ordonnancement problématique :

1. A lance un `arecord` vivant ;
2. B lance un `arecord` qui meurt aussitôt, par exemple micro occupé ;
3. B gagne le `link()` ;
4. A se tue comme perdant ;
5. sans vérification, la session pointerait vers un enregistreur déjà mort.

Le nouveau plan supprime immédiatement la session gagnée à tort, supprime le
petit `.wav`, et lève une erreur visible. C'est le bon comportement. La
reformulation du test en "aucun `arecord` vivant sans session" est aussi la
bonne garantie.

### Le recyclage de PID n'est plus couvert par `_process_exists()`

Je considère ce point résolu sur le fond. Claude retire l'affirmation fausse
selon laquelle `os.kill(pid, 0)` protège contre le recyclage de PID, et remplace
la décision de vivacité par une signature `/proc/<pid>/cmdline` contenant le
chemin du WAV de la session.

Ce n'est pas une preuve cryptographique et il reste une micro-fenêtre TOCTOU
entre le test et le signal, comme avec toute vérification userland suivie d'un
`killpg()`. Mais, pour Aparté, le chemin du WAV est un identifiant de session
suffisamment discriminant : il distingue deux `arecord` simultanés et évite de
signaler un processus recyclé qui n'a aucun lien avec cette capture.

Deux détails d'implémentation à garder en tête, non bloquants :

- utiliser `os.fsencode(session.audio_path)` serait plus exact que
  `str(session.audio_path).encode("utf-8")` pour coller à l'encodage filesystem ;
- ajouter une vérification légère du binaire (`arecord` dans `argv[0]` ou
  `/proc/<pid>/exe`) rendrait le prédicat encore plus lisible, mais le chemin du
  WAV est déjà la signature utile.

## Arbitrage sur le seuil de durée

Claude a raison : mon `wave.open()` n'est pas la bonne source pour ce cas.

Le point décisif est que `wave.open()` croit la taille déclarée dans le chunk
`data`. Or `arecord` initialise un WAV avec une taille maximale avant que la
capture soit terminée, puis corrige le RIFF et le chunk `data` seulement à la
fermeture propre. Le manuel local confirme que SIGINT, SIGTERM et SIGABRT
ferment le fichier, mais SIGKILL ne peut évidemment pas exécuter cette
finalisation.

J'ai vérifié le mécanisme sans toucher au micro utilisateur :

- la commande toggle de `session.py` force `arecord -f S16_LE -r <sample_rate>
  -c 1 <audio_path>` ;
- `arecord` produit WAVE par défaut quand `-t` est omis ;
- le code de capture WAVE d'`alsa-utils` écrit un header RIFF + `fmt ` de 16
  octets + chunk `data`, soit 44 octets pour ce format PCM ;
- sans durée explicite, le plafond de fichier WAV est 2 GiB, ce qui donne
  `0x80000000` octets de données, donc `0x40000000` frames en S16_LE mono ;
- un fichier de 92 044 octets avec cet en-tête placeholder est lu par
  `wave.open()` comme 1 073 741 824 frames, soit 67 108,864 s à 16 kHz, alors
  que `(92044 - 44) / 32000 = 2,875 s`.

Donc mon approche précédente échoue exactement sur l'arrêt brutal qu'elle devait
filtrer. Elle accepterait dix millisecondes réellement captées si le header
annonce encore 18 h 38 min de données.

La méthode de Claude, basée sur la taille réelle du fichier, est la bonne source
pour le chemin toggle actuel :

```python
_WAV_HEADER_BYTES = 44
MIN_TRANSCRIBABLE_SECONDS = 0.3

payload = session.audio_path.stat().st_size - _WAV_HEADER_BYTES
duration = max(0.0, payload / (session.sample_rate * 2))
```

Je ne vois pas, dans le chemin actuel, de cas où la taille mentirait alors que
l'en-tête dirait vrai :

- WAV non-PCM : non, la commande force `S16_LE`, et `arecord` écrit alors
  `WAV_FMT_PCM` ;
- header différent de 44 octets avec `LIST` ou `fact` : non dans ce chemin ;
  `arecord` écrit le `fmt ` canonique de 16 octets puis `data`, sans chunk
  additionnel pour S16_LE PCM ;
- autre nombre de canaux ou autre largeur d'échantillon : non, `-c 1` et
  `S16_LE` sont imposés par `session.py` ;
- fichier sparse ou préalloué : non, `arecord` écrit séquentiellement, il ne
  préalloue pas les 2 GiB du placeholder.

La seule limite réelle est de portée : cette fonction ne doit pas devenir un
parseur WAV générique. Si un futur backend toggle écrit des WAV avec chunks
additionnels, ou si on cesse de forcer S16_LE mono, la constante 44 deviendra
fausse. Dans ce patch, le nom/commentaire doivent donc rester explicitement liés
au WAV `arecord` du toggle.

Il existe aussi une nuance de taux : `alsa-utils` peut sélectionner un taux
effectif proche du taux demandé via ALSA, et l'en-tête propre connaît ce taux
effectif. Mais l'application liste volontairement des périphériques `plughw`,
qui resamplent vers le taux demandé, et le seuil de 0,3 s sert seulement à
rejeter les miettes de démarrage. Cette nuance ne remet pas en cause la méthode
par taille pour le correctif actuel. Si on voulait durcir encore, on pourrait
lire seulement `fmt.sample_fq` / `block_align` dans l'en-tête et ignorer la
longueur `data`, mais ce n'est pas nécessaire pour valider le plan.

## Points encore en débat

Aucun désaccord substantiel ne subsiste.

Je garde trois précisions d'implémentation, mais elles ne bloquent pas le plan :

- nommer la constante de manière contextuelle, par exemple
  `_ARECORD_WAV_HEADER_BYTES = 44`, pour éviter qu'elle soit réutilisée comme
  vérité WAV générale ;
- tester explicitement le cas "header placeholder 0x80000000 mais fichier court"
  pour empêcher une régression vers `wave.open()` ;
- dans `_recorder_alive()`, préférer `os.fsencode()` et éventuellement vérifier
  aussi que le processus ressemble bien à `arecord`.

## Évaluation globale

Je valide le plan dans sa forme actuelle.

Les quatre points bloquants de mon round 2 sont traités à un niveau suffisant :
le seuil devient une durée minimale, les limites de `link()` sont formulées sans
promesse excessive, le gagnant déjà mort est détecté, et la vivacité du recorder
ne repose plus sur un simple test d'existence de PID.

Sur l'arbitrage central, Claude a raison : pour un WAV `arecord` possiblement
tué brutalement, la taille réelle du fichier est plus fiable que la durée lue
depuis l'en-tête.

CONSENSUS_ATTEINT
