# Leçons

Une entrée par correction reçue. Le but n'est pas de raconter l'erreur, c'est
d'écrire la règle qui l'empêche de revenir.

---

## Mesurer sans avoir lu le chemin d'exécution

**22/07.** Conclu deux fois de suite qu'Aparté allait mal, sur la foi d'un banc
d'essai qui ne passait pas par le code d'Aparté.

- Premier coup : appel direct à `faster_whisper.WhisperModel`, donc sans
  `_preload_cuda_libraries()`. Résultat 1,56 s, conclusion « le GPU ne sert
  pas ». Par `build_transcriber()` : 0,24 s. Le GPU servait très bien.
- Deuxième coup : comparaison délégation / processus séparé où seul mon témoin
  forçait `language="fr"`. Conclusion « la délégation est cinq fois plus
  lente ». À réglages égaux : six fois plus rapide.

**Règle.** Un banc d'essai qui contourne la fabrique du projet ne mesure pas le
projet, il mesure une reconstitution. Passer par le point d'entrée réel, ou ne
pas conclure. Et avant d'annoncer un écart, chercher ce qui diffère entre les
deux côtés — un écart d'un facteur cinq est presque toujours une variable non
contrôlée, pas une découverte.

Le détail chiffré est dans `CLAUDE.md` § Mesurer une transcription.

---

## Recommander un réglage contre l'expérience de l'utilisateur

**22/07.** Recommandé de passer Langue sur « Français » : le coût de la
détection est réel et mesuré (0,26 s contre 7,42 s sur un audio pauvre).
Alexandre a répondu qu'il bascule entre français et anglais dans une même
dictée et que le taux d'erreur reste très faible — ce que la mesure ne dit pas.

**Règle.** Un chiffre décrit un cas, pas un usage. Avant de recommander un
changement de réglage, demander comment la personne s'en sert. Et quand le choix
est fait en connaissance de cause, l'écrire à l'endroit où la question
reviendra, pour ne pas la reposer : ici `tasks/todo.md` § À ne pas reprendre.

---

## Empiler du vocabulaire technique dans une question

**22/07, deux fois.** « Je ne comprends pas de quoi on parle et les choix que
j'ai à faire », puis « tu parles notamment de serveurs, mais je sais pas de quoi
il s'agit ».

**Règle.** Une question posée à Alexandre porte sur ce que ça change pour lui,
jamais sur l'architecture. Nommer les choses par leur effet : « le programme
d'arrière-plan » et non « le serveur », « le raccourci clavier » et non « le
chemin CLI ». Si une option ne peut pas se décrire sans son nom de code, c'est
qu'elle n'est pas encore assez comprise pour être proposée.
