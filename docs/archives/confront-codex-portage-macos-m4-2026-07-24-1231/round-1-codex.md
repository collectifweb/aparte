# Round 1 - Codex : revue critique du lot M4

## 1. Ce que j'approuve - choix solides et pourquoi

Le choix principal est bon : ne pas transposer `session.py` sur macOS. Le modèle Linux repose sur un raccourci qui lance des processus CLI éphémères, un fichier de session, `os.link` et `/proc`. Sur macOS, le plan impose déjà un résident avec run loop vivante ; garder l'enregistrement dans ce résident via `RecordingController` est donc le découpage le plus simple et le plus cohérent avec M5. Je ne vois pas de défaut structurel qui obligerait à réécrire le contrôleur pour brancher le raccourci global.

L'injection des dépendances est aussi un bon choix. `transcribe_fn`, `settings_provider`, `clock` et `sample_rate` rendent le coeur testable sous Linux avec un faux `sounddevice` (`src/aparte/macos_recording.py:99-106`, `tests/test_macos_recording.py:67-100`). C'est exactement le bon compromis pour une infra macOS dormante dont l'effet réel sera validé à la main en M8.

La séparation `recording_lock` / `inference_lock` est correcte. Le contrôleur protège sa machine d'état avec son propre verrou (`src/aparte/macos_recording.py:112-143`), tandis que `desktop.py` garde le verrou modèle autour de la transcription serveur (`src/aparte/desktop.py:497-503`). Mélanger ces deux responsabilités rendrait la capture dépendante de l'aperçu navigateur ou d'une transcription longue.

La transcription serveur-locale, sans self-HTTP, est la bonne couture. `_transcribe_capture()` réutilise le cache de transcripteur et `inference_lock` directement (`src/aparte/desktop.py:497-503`). Cela respecte l'invariant Darwin : aucune route HTTP ne déclenche un effet système. La route ajoutée, `GET /api/recording-state`, est purement observatrice (`src/aparte/desktop.py:273-282`) et les routes POST à effet système restent désactivées sur Darwin (`src/aparte/desktop.py:42-49`, `src/aparte/desktop.py:285-293`).

L'extraction de `deliver_transcript()` est saine. Les invariants "texte vide -> rien", "historique avant insertion", "notification après insertion" sont réellement partagés par `dictate_once`, `toggle_dictation` et le worker macOS (`src/aparte/cli.py:321-338`). Les tests verrouillent cet ordre (`tests/test_cli.py:96-119`) et évitent une divergence silencieuse sur le chemin macOS.

Le worker hors fil déclencheur est nécessaire. `_stop_locked()` passe à `processing`, détache un worker, puis la transcription et l'insertion ont lieu hors callback audio et hors fil de raccourci (`src/aparte/macos_recording.py:208-239`). C'est la bonne direction pour M5 : le raccourci ne doit pas attendre Whisper.

Les tests couvrent une bonne partie du contrat observable : start/stop, flux `RawInputStream`, tampon borné, transcription vide, erreur de transcription, erreur de fermeture, debounce, cap timer, absence de `sounddevice`, WAV 16 kHz mono int16 (`tests/test_macos_recording.py:116-260`). J'ai relancé les tests ciblés de M4/M3 autour de ce périmètre : 25 tests, verts.

## 2. Ce que je désapprouve - choix erronés, avec arguments techniques

Le plus gros problème est la concurrence entre le callback PortAudio et l'arrêt. `_callback()` écrit directement dans `self._frames`, `self._frame_count`, `_truncated` et `_overflowed`, sans verrou, sans vérifier l'état courant et sans jeton de génération (`src/aparte/macos_recording.py:194-205`). Or `_stop_locked()` détache `frames = self._frames`, remplace `self._frames` par une nouvelle liste, passe en `processing`, puis seulement le worker ferme le stream (`src/aparte/macos_recording.py:208-225`). Tant que `_close_stream()` n'a pas réellement arrêté le stream, un callback tardif peut écrire dans le nouveau `self._frames`, donc hors snapshot transcrit. Si `stop()` ou `close()` échoue vraiment, `_close_stream()` avale l'erreur (`src/aparte/macos_recording.py:275-289`) et le contrôleur peut revenir à `idle` avec un ancien stream encore capable d'écrire dans le tampon d'une capture future. C'est un vrai défaut de correction, pas un goût d'architecture. A corriger avant M5.

L'ordre du bip de démarrage est faux. `play_beep()` documente que le bip d'ouverture doit être terminé avant que le micro démarre, sinon il entre dans l'enregistrement (`src/aparte/audio.py:169-174`). Le chemin Linux respecte ça : `dictate_once()` et `toggle_dictation()` jouent le bip avant d'ouvrir l'enregistrement (`src/aparte/cli.py:263-269`, `src/aparte/cli.py:358-364`). Le contrôleur macOS fait l'inverse : il démarre `RawInputStream`, arme l'état, puis joue le bip (`src/aparte/macos_recording.py:183-192`). Avec `beep=True`, le début de chaque dictée macOS risque donc de contenir le bip. Le bip d'arrêt est aussi joué alors que le stream physique est encore ouvert, même si le snapshot a déjà été détaché (`src/aparte/macos_recording.py:208-221`). Ce n'est pas bloquant architecturalement, mais c'est une correction avant usage réel.

Le chemin in-process ne polit pas le texte. Le docstring du contrôleur promet que les changements de `polish` prennent effet sans redémarrage (`src/aparte/macos_recording.py:25-26`) et le plan global décrit `processing` comme transcription -> polissage -> insertion (`docs/plan-portage-macos.md:88-92`). En réalité, `_transcribe_capture()` ne fait que `transcribe(wav).text` (`src/aparte/desktop.py:497-499`), puis le worker appelle `deliver_transcript()` (`src/aparte/macos_recording.py:233-253`). Or `deliver_transcript()` ne polit pas ; la CLI polit avant de livrer via `transcribe_path()` (`src/aparte/cli.py:258-260`, `src/aparte/cli.py:371-378`). Le futur raccourci macOS livrera donc du texte brut là où le raccourci Linux livre par défaut le texte poli. C'est une régression fonctionnelle du chemin M5, corrigeable dans `_transcribe_capture()` ou dans une fonction de traitement partagée, sans réécrire le contrôleur.

Les transitions d'arrêt ont des trous d'erreur après mutation d'état. Dans `_stop_locked()`, le contrôleur annule le timer, détache le stream, vide `self._frames`, passe en `PROCESSING`, puis relit les settings pour le bip et démarre le worker (`src/aparte/macos_recording.py:208-221`). Si `settings_provider()` lève à ce moment-là, par exemple config JSON corrompue, ou si `Thread.start()` lève sous épuisement de threads, le stream n'est pas fermé, les frames ne sont plus accessibles par le contrôleur et l'état reste `processing`. C'est le même type de défaut que la fuite `_arm_cap_timer`, mais sur le stop, donc plus directement exposé dès M5.

La promesse "le handler rend la main tout de suite" est trop forte. Il ne transcrit pas sur le fil déclencheur, c'est vrai. Mais `toggle()` garde `_lock` pendant `settings_provider()`, import/ouverture `sounddevice`, `RawInputStream.start()`, `Timer.start()`, les bips et certaines notifications (`src/aparte/macos_recording.py:131-166`, `src/aparte/macos_recording.py:168-192`, `src/aparte/macos_recording.py:312-316`). Sur M5, si le callback AppKit appelle `toggle()` directement sur la run loop, il peut encore bloquer sur de l'I/O système ou des sous-processus courts. Cela ne force pas à réécrire le contrôleur, mais M5 doit soit assumer cette latence, soit dispatcher l'appel hors run loop.

## 3. Ce qui manque - cas non traités, chemins d'erreur oubliés, risques de concurrence non identifiés

Il manque des tests qui font tourner le callback après stop/shutdown. Le fake actuel appelle `feed()` uniquement dans les phases attendues. Il ne couvre pas le cas critique : `_stop_locked()` a remplacé `self._frames`, mais l'ancien stream appelle encore `callback`. Il faut un test qui nourrit le callback après le stop, et idéalement un test où `close()` échoue, pour prouver que l'ancien stream ne peut pas contaminer une capture suivante.

Il manque un test sur l'ordre des bips. Avec `beep=True`, le test devrait prouver que le bip de démarrage se produit avant `stream.start()` ou, si le choix produit est différent, documenter explicitement que le bip est capturé. L'état actuel contredit le commentaire de `play_beep()` et le comportement Linux.

Il manque un test du chemin "worker impossible à démarrer". Le code teste une erreur `RawInputStream.start()` (`tests/test_macos_recording.py:243-247`) et une erreur `stream.stop()` (`tests/test_macos_recording.py:190-196`), mais pas `Thread.start()` ni `settings_provider()` qui lève pendant `_stop_locked()`. Ces erreurs sont rares, mais elles arrivent au pire moment : après avoir déplacé l'état en `processing`.

Il manque l'intégration de `shutdown()` au cycle de vie du serveur. `shutdown()` est testé isolément (`tests/test_macos_recording.py:225-233`), mais `run_desktop()` ne l'appelle pas dans son `finally`; il ne fait que `server.server_close()` (`src/aparte/desktop.py:98-108`). En M4 dormant, ça n'a aucun effet pratique. En M5/M6, si une capture ou un worker est actif pendant `Quitter`, le contrat "discard propre au shutdown" ne sera pas réellement exercé par l'application.

Il manque une surface d'état plus riche pour les erreurs utiles. Pour M4, `{"state": "idle|recording|processing|error"}` suffit. Mais `_truncated`, `_overflowed` et la dernière exception ne sortent nulle part. Ce n'est pas nécessaire pour brancher M5, mais ce sera nécessaire si M6 veut afficher autre chose qu'un voyant binaire ou si M8 doit diagnostiquer une capture réelle dégradée.

Il manque la parité "polissage avant livraison" dans les tests d'intégration serveur. `RecordingStateRouteTest` prouve que `_transcribe_capture()` utilise le modèle serveur et pas HTTP (`tests/test_desktop.py:482-494`), mais il ne vérifie pas que le texte livré par le raccourci suit la même chaîne que Linux : transcription, polissage selon settings, historique, insertion.

## 4. Ce que je remettrais en question - décisions discutables

L'attribut de classe `DesktopHandler._recording_controller` est acceptable pour M4, mais je ne le figerais pas comme point d'ancrage long terme. M5 peut techniquement le récupérer via la classe handler retournée par `handler_factory()` ou via `server.RequestHandlerClass`, donc ça ne bloque pas. Mais le propriétaire naturel du contrôleur est le processus desktop/run loop, pas le handler HTTP. En M5, je préférerais que `run_desktop()` garde une référence explicite au contrôleur et la passe au hotkey/tray, quitte à laisser le handler l'observer.

Le worker daemon est discutable. Il simplifie la fermeture, mais il rend assumée la perte d'une insertion en cours au moment où le processus quitte (`src/aparte/macos_recording.py:218-220`). Pour M4 dormant, c'est acceptable. Pour M6, avec un menu "Quitter" et peut-être "Mettre à jour", il faudra choisir explicitement : soit abandon immédiat documenté, soit `join()` borné, soit état "closing" sans nouveau toggle.

Le debounce global à 250 ms est défendable, mais la sémantique devrait rester liée au problème réel de M5 : filtrer les répétitions d'événement du raccourci. Tel quel, il avale aussi un stop volontaire ultra-rapide. Comme 250 ms est sous le seuil minimal transcrivable de 300 ms (`src/aparte/macos_recording.py:62-66`), je ne le corrigerais pas maintenant, mais je surveillerais la source exacte des événements M5. Si RegisterEventHotKey ne duplique pas les événements, un debounce moins agressif ou limité à `IDLE/ERROR -> RECORDING` serait plus propre.

La redondance plafond en frames + cap timer est bonne et je ne la retirerais pas. Le timer donne l'auto-stop produit ; le plafond en frames protège la mémoire si le timer est retardé, bloqué ou si le flux audio produit plus vite que prévu. Le test montre toutefois que le plafond n'est pas exact à la frame près : le chunk qui franchit le seuil est encore accepté (`tests/test_macos_recording.py:143-154`). C'est acceptable comme borne "max + un callback block", mais il ne faut pas le décrire comme un plafond strict.

Le helper `deliver_transcript()` dans `cli.py` est acceptable maintenant malgré le lazy import depuis le worker. Si le code de livraison grossit encore, il faudra probablement le sortir de `cli.py` vers un module neutre pour que le contrôleur ne dépende pas conceptuellement de la couche commande. Je ne ferais pas cette extraction en M4 : le lazy import actuel règle le cycle et limite les changements.

## Traitement des 6 zones faibles listées par Claude

| Zone faible | Verdict |
|---|---|
| `_truncated` / `_overflowed` posés mais jamais lus | Ne bloque pas M5. Bruit acceptable pour M4 dormant. A reprendre en M6/M8 si l'état doit diagnostiquer une capture tronquée ou un overflow réel. |
| `shutdown()` ne couvre que `RECORDING`, pas `PROCESSING` | Ne bloque pas M5. Le vrai manque immédiat est plutôt que `run_desktop()` n'appelle pas `shutdown()` du tout. A traiter avec le cycle de vie M5/M6 ; un `join()` borné peut attendre. |
| Debounce qui peut avaler un stop volontaire | Ne bloque pas M5. Acceptable tant que l'objectif est de filtrer les doubles événements du raccourci et que la fenêtre reste sous le seuil transcrivable. A réviser seulement après observation de RegisterEventHotKey. |
| Fuite théorique de stream si `_arm_cap_timer` lève | Correction à faire maintenant ou avant M5. Ce n'est pas structurel, mais le fix est chirurgical : le `except` de `_begin_locked()` doit fermer le stream courant avant de l'oublier. |
| Redondance plafond-frames / cap-timer | Pas un problème. Garder les deux : le timer arrête, le plafond protège la mémoire. Clarifier seulement que le plafond accepte au plus un chunk au-delà du seuil. |
| `_recording_controller` comme attribut de classe du handler | Ne bloque pas M5, mais à ne pas sanctuariser. M5 devrait idéalement donner au hotkey une référence explicite au contrôleur plutôt que faire de la classe HTTP le registre applicatif. |

## Verdict M4 -> M5

Le découpage M4 est globalement bon : in-process, sans self-HTTP, sans portage artificiel de `session.py`, avec un contrôleur testable et un worker hors transcription. Je ne vois pas de raison de jeter ce contrôleur.

En revanche, je ne brancherais pas M5 sans corriger au minimum trois points : isoler le callback des callbacks tardifs / streams mal fermés, remettre les bips hors capture, et restaurer le polissage dans le chemin in-process. Les deux premiers touchent la correction de capture ; le troisième touche la parité fonctionnelle du raccourci. Ce sont des corrections chirurgicales, pas une remise en cause du découpage.
