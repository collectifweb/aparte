# Round 4 - Reponse Codex

## Point resolu (l'update HTTP)

Je confirme que mon unique objection restante du round 3 est levee.

Le round 3 refusait le consensus pour une seule raison precise : `/api/update/apply`
restait exposee en HTTP sur Darwin, alors que la frontiere demandee devait empecher
le navigateur macOS de declencher un update applicatif.

Claude concede explicitement ce point au round 4 : sur Darwin,
`POST /api/update/apply` est desactivee, et l'update macOS passe par une action native
du tray, en appel in-process direct a la logique d'update, ou par `aparte update` en
CLI. Elle ne passe donc plus par l'UI navigateur ni par une route HTTP.

J'ai aussi verifie que le tableau final couvre bien la surface HTTP actuelle de
`desktop.py` : les routes restantes en ecriture cote HTTP macOS sont limitees a
`/api/transcribe`, `/api/polish`, `/api/config` et `/api/history`, c'est-a-dire des
operations de texte ou de donnees applicatives. Les actions que je visais
explicitement au round 3 sortent toutes de la surface HTTP Darwin :

- presse-papiers serveur : `/api/copy` desactivee ;
- clavier / insertion : `/api/paste` desactivee ;
- update applicatif : `/api/update/apply` desactivee ;
- launchd, installation de raccourci et permissions : deja hors HTTP, conserves en
  natif ou CLI.

Cette correction aligne la frontiere finale avec la voie A acceptee : le navigateur
local peut produire et manipuler du texte applicatif, mais ne peut pas piloter une
action native ou systeme.

## Points encore en debat

Aucun.

Je ne rouvre pas les points deja resolus : TCC, `RecordingController`, run loop
AppKit, delegation CLI pure, faster-whisper CPU en v1, acquisition des modeles,
historique runtime, `quickmachotkey`, tests et smoke suite ont deja ete acceptes ou
integres dans les rounds precedents.

## Evaluation globale

Le plan me convient maintenant. La concession sur `/api/update/apply` clot la seule
objection substantielle restante : aucune route HTTP a effet systeme ne reste exposee
sur Darwin, tandis que les routes web conservees restent dans le perimetre applicatif
attendu.

Je valide donc le consensus et considere que le plan peut etre consolide dans
`docs/plan-portage-macos.md`.

CONSENSUS_ATTEINT
