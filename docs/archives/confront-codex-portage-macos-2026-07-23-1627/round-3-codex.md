# Round 3 - Reponse Codex

## Points resolus depuis le round precedent

### Delegation CLI et suppression du proxy HTTP principal

Claude integre correctement le coeur de ma demande sur la delegation CLI :

- pas de `/api/toggle` sur macOS ;
- le raccourci natif appelle `RecordingController` directement, in-process ;
- la bascule a deux appuis n'est fournie que par le raccourci resident ;
- la seule delegation HTTP de la CLI reste `transcribe_via_running_app()` : envoyer
  un fichier audio, recevoir du texte, sans enregistrement serveur, sans insertion,
  sans historique et sans effet systeme.

Je valide aussi la decision de desactiver `/api/paste` sur Darwin et de neutraliser
`/api/copy` au profit de `navigator.clipboard.writeText` sous geste utilisateur. Cela
repond a la critique sur le serveur resident comme proxy d'Accessibilite, sans
reintroduire un token ou une IPC inutile pour une route qui n'a plus besoin
d'exister.

Le fait que Claude ne liste pas toutes les routes purement textuelles ou de lecture
comme `/api/polish`, `/api/doctor` ou `/api/microphones` n'est pas bloquant pour ce
round : elles ne changent pas la frontiere demandee sur les routes a effet systeme.

### Acquisition des modeles faster-whisper et promesse "tout local"

Le point est maintenant suffisamment integre. Claude constate explicitement que
`WhisperModel(self.model_name, ...)` peut telecharger un modele au premier usage si le
cache local est vide, puis tranche une strategie claire :

- `install-macos.sh` propose un prechargement avec consentement reseau explicite ;
- `doctor` signale si le modele est deja local ou si la premiere transcription devra
  le recuperer ;
- la documentation reformule la promesse : l'audio et le texte ne quittent jamais la
  machine, mais le modele peut etre telecharge une fois, sauf prechargement.

Je valide ce point. Je ne demande pas de reecrire le chemin `WhisperModel` ni
d'ajouter `local_files_only` en prealable a la v1 macOS, tant que l'installation, le
diagnostic et la documentation portent cette nuance clairement.

### Historique runtime macOS

La precision documentaire sur `$TMPDIR` macOS est aussi acceptee : le fichier runtime
`0600` reste le bon compromis, avec une promesse nuancee sur l'effacement qui n'est pas
equivalente au tmpfs systemd Linux.

## Points encore en debat

### `/api/update/apply` reste exposee en HTTP sur Darwin

Il reste un manque precis dans le point 1. Au round 2, ma demande ne se limitait pas
aux permissions TCC. Je demandais explicitement que le navigateur macOS ne puisse pas
declencher d'update applicatif, et que les routes touchant presse-papiers, clavier,
update, launchd ou permissions soient sorties de la surface HTTP Darwin.

Claude classe bien `/api/update/apply`, mais choisit de la garder :

> `POST /api/update/apply` : `git merge --ff-only` + `pip install` + redemarrage ;
> gardee, avec redemarrage via bundle/LaunchAgent.

C'est la seule decision que je ne peux pas valider. Une route qui lance `git`/`pip` et
redemarre l'application via bundle ou LaunchAgent reste une route HTTP a effet systeme,
meme si elle ne consomme pas Microphone ou Accessibilite. Le critere "un process local
pourrait faire pareil" etait justement le critere Linux que nous avions decide de ne
pas reprendre tel quel pour macOS. Le garde-fou Origin/loopback ne resout pas ce point :
la page servie par l'application peut toujours declencher l'update, et le test "sans
Origin" ne retire pas cette surface navigateur.

Ce qui manque encore est donc tres limite : le plan consolide doit sortir
`/api/update/apply` de la surface HTTP Darwin, ou au minimum dire explicitement que
l'update macOS passe par un chemin non-web, par exemple commande CLI ou action native du
bundle, pas par une route appelee depuis l'UI navigateur. Je ne redemande pas de token
pour `/api/paste` ou `/api/toggle` : ces routes sont correctement supprimees ou
neutralisees. Le point restant est uniquement l'update applicatif par HTTP.

## Evaluation globale

Le debat est quasiment clos : architecture residente, `RecordingController`, run loop
AppKit unique, TCC assume, faster-whisper CPU en v1, whisper.cpp/Metal post-v1,
strategie de modele local et delegation CLI pure sont maintenant valides.

Je refuse le consensus seulement parce que la frontiere HTTP demandee au round 2 n'est
pas appliquee jusqu'au bout a `/api/update/apply`. Si Claude retire cette route de la
surface HTTP Darwin dans le plan consolide, je n'ai plus d'objection substantielle.

CONSENSUS_REFUSE — Au moins un point reste réellement en débat ou un manque subsiste.
