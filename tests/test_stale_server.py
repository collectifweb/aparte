"""Le serveur d'avant la mise à jour tient le port, et il faut le lui reprendre.

Scénario d'origine, vécu le 31/07 : une session ouverte avant le renommage
Murmur → Aparté gardait son serveur en vie depuis six jours. Le `git pull` a
déplacé ses fichiers statiques, qu'il relit sur le disque à chaque requête ; son
code, lui, était déjà en mémoire. Résultat : une API qui répond parfaitement et
une page d'accueil en 404. L'installation réussissait, et lancer Aparté ouvrait
le navigateur sur cette page d'erreur.
"""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from aparte import stale_server
from aparte.config import Settings
from aparte.desktop import handler_factory
from aparte.stale_server import names_our_desktop_server, reclaim_port

needs_proc = unittest.skipUnless(
    Path("/proc/net/tcp").exists(), "la reprise de port lit /proc (Linux seulement)"
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class CommandLineSignatureTest(unittest.TestCase):
    """Le PID ne prouve rien — le noyau les recycle. L'identité se lit sur la
    ligne de commande, et elle doit tenir les deux formes de lancement."""

    def test_recognises_the_module_form_under_the_old_name(self):
        argv = ["/home/a/.venv/bin/python", "-m", "murmur", "desktop", "--no-browser"]
        self.assertTrue(names_our_desktop_server(argv))

    def test_recognises_the_console_script_form(self):
        argv = ["/home/a/.venv/bin/python", "/home/a/.venv/bin/aparte", "desktop"]
        self.assertTrue(names_our_desktop_server(argv))

    def test_refuses_another_application(self):
        self.assertFalse(names_our_desktop_server(["/usr/bin/python3", "-m", "http.server"]))

    def test_refuses_another_subcommand(self):
        argv = ["/home/a/.venv/bin/python", "/home/a/.venv/bin/aparte", "dictate"]
        self.assertFalse(names_our_desktop_server(argv))

    def test_refuses_a_path_that_merely_contains_the_name(self):
        """L'installation vit dans ``~/murmur`` : le nom traîne dans des chemins
        qui n'ont rien à voir avec le serveur. Un SIGTERM sur cette foi tuerait
        le processus de quelqu'un d'autre."""
        argv = ["/usr/bin/python3", "/home/alexandre/murmur/scripts/sauvegarde.py", "desktop"]
        self.assertFalse(names_our_desktop_server(argv))

    @needs_proc
    def test_the_test_runner_is_not_taken_for_a_server(self):
        self.assertFalse(stale_server._is_our_server(os.getpid()))


@needs_proc
class ListenerLookupTest(unittest.TestCase):
    def test_finds_the_process_holding_a_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            inode = stale_server._listening_inode("127.0.0.1", port)
            self.assertIsNotNone(inode)
            self.assertEqual(stale_server._pid_owning(inode), os.getpid())

    def test_nothing_to_find_when_nobody_listens(self):
        self.assertIsNone(stale_server._listening_inode("127.0.0.1", free_port()))


@needs_proc
class ReclaimPortTest(unittest.TestCase):
    def test_a_healthy_server_is_left_alone(self):
        """Le contrôle décisif est la page, pas l'API. Un serveur qui sert encore
        la sienne est vivant, quoi qu'en dise le reste."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(Settings()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_port

        self.assertIsNone(reclaim_port("127.0.0.1", port))
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            self.assertEqual(response.status, 200)

    def test_a_stranger_holding_the_port_is_left_alone(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertIsNone(reclaim_port("127.0.0.1", port, probe_timeout=0.5))
            self.assertIsNotNone(stale_server._listening_inode("127.0.0.1", port))

    def test_nothing_listening_is_not_an_error(self):
        self.assertIsNone(reclaim_port("127.0.0.1", free_port(), probe_timeout=0.5))

    def test_the_stale_server_is_stopped_and_the_port_comes_back(self):
        """Le scénario complet, avec un vrai processus : il porte notre nom, il
        écoute, et il répond 404 à sa propre page — exactement le serveur que la
        mise à jour laisse derrière elle."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        # Le nom du fichier fait la signature : c'est la forme `.../bin/aparte`.
        script = Path(directory.name) / "aparte"
        script.write_text(
            "import http.server, sys\n"
            "class Handler(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_error(404)\n"
            "    def log_message(self, *args):\n"
            "        pass\n"
            "server = http.server.HTTPServer(('127.0.0.1', 0), Handler)\n"
            "print(server.server_port, flush=True)\n"
            "server.serve_forever()\n",
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [sys.executable, str(script), "desktop"],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(process.kill)
        self.addCleanup(process.stdout.close)
        port = int(process.stdout.readline().strip())

        self.assertEqual(reclaim_port("127.0.0.1", port), process.pid)
        self.assertEqual(process.wait(timeout=5), -15)  # SIGTERM
        self.assertIsNone(stale_server._listening_inode("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
