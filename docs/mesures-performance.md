# Mesurer les délais de dictée

Instrumentation du lot 4 Linux, incluse dans la version 1.3.0.
Elle devient active sur une installation après mise à jour vers cette version.
Les 60–80 secondes rapportées par Alexandre ne sont pas encore expliquées par
une mesure sur son poste. La langue Auto et le modèle choisi restent inchangés.

## Ce qui est mesuré

Le raccourci suit une opération depuis la prise en charge de l'audio arrêté
jusqu'à sa livraison et au nettoyage. Le temps passé à parler, l'arrêt du micro,
le bip et la notification initiale de transcription sont hors de ce total.

| Étape | Ce que comprend sa durée |
| --- | --- |
| `delegation` | Recherche de l'application résidente, transfert et attente de sa réponse ; un repli local peut suivre. |
| `queue` | Attente du verrou du modèle partagé ; un aperçu occupé renonce immédiatement. |
| `model_load` | Construction d'un modèle absent du cache, ou rechargement CPU après un échec CUDA tardif. |
| `transcription` | Appel complet du transcripteur, incluant consommation des segments différés et nettoyage des hallucinations. |
| `polish` | Construction du polisseur et mise en forme du texte. |
| `delivery` | Historique et livraison CLI, incluant copie/insertion et notification. |

Chaque événement porte un `trace_id` aléatoire, une source (`shortcut`, `cli`,
`http`, `preview`, `recovery`) et un horodatage UTC. Les durées en millisecondes
utilisent une horloge monotone. Le raccourci transmet son identifiant au serveur
local par `X-Aparte-Trace` ; le serveur refuse les identifiants qui ne sont pas
32 caractères hexadécimaux minuscules et en crée alors un nouveau.

Le total CLI et le total HTTP d'une même dictée **se recouvrent**. De même, le
chargement CPU tardif est inclus dans la transcription. Ne pas additionner tous
les événements. L'absence de `model_load` sur un appel servi depuis le cache est
normale. Un appel CLI imbriqué conserve l'opération en cours, sans second total.

Les transcriptions/imports et polissages HTTP sont aussi mesurés, ainsi que les
réessais de récupération. Les requêtes distinctes du navigateur ont des traces
distinctes : il n'existe pas encore de total navigateur couvrant transcription,
polissage et insertion. La transcription CLI autonome est mesurée, mais sa
sortie finale via `handle_output` reste hors de ce total.

## Informations techniques et confidentialité

- `performance_execution` : moteur, modèle standard, appareil et type de calcul
  effectifs quand ils sont exposés par le moteur. Pour faster-whisper, lecture
  sur le modèle CTranslate2 chargé, jamais déduction depuis le réglage « auto ».
  Valeurs indisponibles ou non reconnues : `unknown`. Un repli tardif émet les
  informations avant et après le changement. Aucun chemin de modèle personnalisé.
- `performance_audio` : durée issue des métadonnées WAV, sans lecture des
  échantillons ; omise si le format, les permissions ou l'en-tête ne conviennent
  pas. Les fichiers spéciaux et liens symboliques sont refusés par cette mesure.
- `performance_total` : durée, succès/échec, classe d'erreur autorisée uniquement,
  code HTTP lorsqu'il a été renseigné, charge moyenne sur une minute (`load1`) et
  nombre de processeurs logiques (`cpu_count`) observés au départ. La charge
  moyenne n'est ni un pourcentage CPU, ni une mesure GPU ou de mémoire saturée.

Le journal reste local : `$XDG_STATE_HOME/aparte/logs/hotkey.jsonl`, ou
`~/.local/state/aparte/logs/hotkey.jsonl`, et sa rotation `.1`. Dossiers privés,
fichiers 0600, deux fichiers de 128 Kio maximum. Les événements de performance
n'acceptent ni texte dicté, ni vocabulaire, ni chemin audio, ni message libre
d'exception. Une requête HTTP terminée normalement avec un code d'erreur marque
son total en échec.

La journalisation reste facultative pour le succès de la dictée : panne disque,
contention ou rotation peuvent faire manquer des événements. Une trace incomplète
ne prouve donc pas qu'une étape n'a pas été exécutée. Le journal contient aussi
les événements techniques du raccourci ; filtrer les événements `performance_*`
et leur identifiant pour analyser un délai.

## Prochaine mesure sur le poste

Après livraison, comparer quelques dictées de durée connue, en distinguant le
premier usage du modèle des suivants. Relever les étapes les plus longues, le
matériel effectif et la charge ; ne pas conclure à partir du seul nom `small`.
Conserver les réglages pour cette première comparaison, et ne pas réutiliser
d'enregistrement personnel sans accord. Un test synthétique valide l'attribution
des mesures, pas les performances de Whisper sur le poste ni le retour de veille.
