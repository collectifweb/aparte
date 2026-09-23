"""Reprendre le port d'un serveur de bureau à nous qui ne sert plus rien.

Le cas qui a donné ce module : une session ouverte avant le renommage
Murmur → Aparté garde son serveur en vie. Le `git pull` de la mise à jour
déplace `src/murmur/` sous ses pieds, mais son code Python est déjà en mémoire,
donc ses routes API répondent encore parfaitement. Ses fichiers statiques, eux,
sont relus sur le disque **à chaque requête** : ils ont disparu. Le serveur
survit donc en répondant 404 à sa propre page, et il tient toujours le port.

Lancer Aparté par-dessus se contentait de repérer une API vivante et lui passait
la main : l'utilisateur recevait une page 404 après une installation annoncée
réussie. Repartir sur un port au hasard n'aurait pas mieux valu — le raccourci
de dictée délègue au 8765 en dur, et n'aurait plus trouvé personne.

Linux seulement : tout passe par `/proc`. Ailleurs, chaque fonction rend None,
et l'appelant retombe sur sa recherche de port habituelle.
"""

from __future__ import annotations

import os
import signal
import socket
import time
import urllib.request
from http import HTTPStatus
from pathlib import Path, PurePosixPath

# Les deux noms sous lesquels l'application a pu être lancée. « murmur » reste
# indispensable : c'est justement le serveur d'avant le renommage qu'on vient
# ramasser, et sa ligne de commande porte encore l'ancien nom.
APP_NAMES = ("aparte", "murmur")

# L'état d'une socket en écoute, tel que /proc/net/tcp l'écrit.
_TCP_LISTEN = "0A"

# Toutes adresses, quand le serveur n'a pas été lié à une interface précise.
_ANY_ADDRESS = "00000000"

_TERM_GRACE_SECONDS = 5.0
_PROBE_TIMEOUT = 2.0


def reclaim_port(
    host: str,
    port: int,
    grace: float = _TERM_GRACE_SECONDS,
    probe_timeout: float = _PROBE_TIMEOUT,
) -> int | None:
    """Arrêter le serveur mort qui tient ce port. Son PID, ou None si rien à faire.

    Trois refus, dans cet ordre, et chacun compte :

    - **Personne n'écoute** : il n'y a rien à reprendre.
    - **La page se sert encore** : c'est un serveur vivant, on n'y touche pas.
      Ce contrôle passe avant tout le reste parce qu'il est le seul qui distingue
      vraiment un mort d'un vivant — une API qui répond ne prouve que la mémoire
      du processus, jamais que ses fichiers sont encore là.
    - **Ce n'est pas nous** : un SIGTERM au petit bonheur tuerait le processus de
      quelqu'un d'autre. L'identité se prouve sur `/proc`, jamais sur le PID seul.
    """
    inode = _listening_inode(host, port)
    if inode is None:
        return None
    if _serves_its_page(host, port, probe_timeout):
        return None
    pid = _pid_owning(inode)
    if pid is None or pid == os.getpid() or not _is_our_server(pid):
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return None
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if _listening_inode(host, port) is None:
            return pid
        time.sleep(0.1)
    # Toujours là : on rend le port à l'appelant plutôt que d'escalader en
    # SIGKILL. Il repartira sur un autre port, ce qui reste préférable à tuer
    # de force un processus qui refuse de partir pour une raison qu'on ignore.
    return None


def _listening_inode(host: str, port: int) -> str | None:
    """Le numéro d'inœud de la socket en écoute sur host:port, s'il y en a une."""
    try:
        packed = socket.inet_aton(socket.gethostbyname(host))
    except OSError:
        return None
    # /proc/net/tcp écrit l'adresse en hexadécimal, dans l'ordre d'octets de
    # l'hôte : 127.0.0.1 s'y lit 0100007F.
    addresses = {f"{int.from_bytes(packed, 'little'):08X}", _ANY_ADDRESS}
    try:
        rows = Path("/proc/net/tcp").read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        return None
    for row in rows:
        fields = row.split()
        if len(fields) <= 9 or fields[3].upper() != _TCP_LISTEN:
            continue
        local, _, local_port = fields[1].upper().rpartition(":")
        if local in addresses and local_port == f"{port:04X}":
            return fields[9]
    return None


def _pid_owning(inode: str) -> int | None:
    """Le processus qui détient cette socket. None si aucun des nôtres ne l'a.

    On ne peut lire les descripteurs que de nos propres processus, et c'est
    exactement ce qu'il faut : un serveur qu'on ne pourrait pas inspecter est un
    serveur qu'on n'a pas le droit d'arrêter.
    """
    target = f"socket:[{inode}]"
    try:
        entries = sorted(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            descriptors = list((entry / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                if os.readlink(descriptor) == target:
                    return int(entry.name)
            except OSError:
                # Un descripteur fermé entre l'inventaire et la lecture. Les
                # suivants restent à voir : c'est peut-être l'un d'eux.
                continue
    return None


def _serves_its_page(host: str, port: int, timeout: float) -> bool:
    """Ce serveur rend-il encore sa page d'accueil ?

    C'est la question qui manquait. Elle porte sur un fichier relu sur le disque,
    donc elle échoue précisément quand une mise à jour a déplacé l'installation
    sous un processus déjà lancé. La route est un simple `read_bytes` sans
    verrou : un serveur occupé à transcrire y répond quand même.
    """
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=timeout) as response:
            return response.status == HTTPStatus.OK
    except OSError:
        return False


def _is_our_server(pid: int) -> bool:
    """Ce processus est-il un serveur de bureau à nous, et à nous seuls ?"""
    try:
        if Path(f"/proc/{pid}").stat().st_uid != os.getuid():
            return False
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return names_our_desktop_server(raw.decode("utf-8", "replace").split("\0"))


def names_our_desktop_server(argv: list[str]) -> bool:
    """Cette ligne de commande est-elle « aparte desktop » ou son ancien nom ?

    Deux signatures, dans le même esprit que `_recorder_alive` : la
    sous-commande **et** le programme. Et le programme ne se cherche qu'aux deux
    premières places — `python -m aparte` ou `.../bin/aparte` — parce qu'un
    chemin passé en argument peut contenir « murmur » sans que le processus soit
    le nôtre. C'est le cas ici même : l'installation vit dans `~/murmur`.
    """
    argv = [part for part in argv if part]
    if "desktop" not in argv:
        return False
    if len(argv) >= 3 and argv[1] == "-m" and argv[2] in APP_NAMES:
        return True
    return any(PurePosixPath(part).name in APP_NAMES for part in argv[:2])
