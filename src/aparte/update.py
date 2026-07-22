"""Update Aparté in place, from the git checkout it runs from.

There is no release binary to download and no update server: an install is a
clone plus `pip install -e .`, so an update is `git pull` plus the same install
command. What needs care is refusing the situations where pulling would lose
work or silently do nothing.

Nothing here touches the network unless it is asked to: `check_update()` only
fetches when told to, so opening the diagnostics panel stays offline.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from .diagnostics import _has_module

# Written on its own line at the end of a successful update, so the browser can
# tell "the log stopped" from "the update worked".
DONE_MARKER = "__APARTE_UPDATED__"

FETCH_TIMEOUT = 30  # git fetch reaches the network
GIT_TIMEOUT = 10  # everything else is local


def find_repo() -> Path | None:
    """The git checkout Aparté runs from, or None when it was installed as a copy."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def check_update(fetch: bool = False) -> dict:
    """Describe what an update would do right now, without doing any of it.

    States: manual (not a checkout), no_upstream, offline, error, current,
    available. `dirty` is reported alongside rather than as a state — the user
    still wants to see that four commits are waiting, even when the checkout is
    too dirty to pull them.
    """
    repo = find_repo()
    if repo is None:
        return {"state": "manual"}

    try:
        upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if upstream.returncode != 0:
            branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            return {"state": "no_upstream", "repo": str(repo), "branch": branch}

        # The remote is whatever this branch actually tracks. Do not assume
        # "origin": on the author's machine it is called "Murmur".
        upstream_ref = upstream.stdout.strip()
        remote = upstream_ref.split("/", 1)[0]
        head = _git(repo, "log", "-1", "--format=%h %s").stdout.strip()
        dirty = bool(_git(repo, "status", "--porcelain").stdout.strip())

        if fetch:
            fetched = _git(repo, "fetch", "--quiet", remote, timeout=FETCH_TIMEOUT)
            if fetched.returncode != 0:
                detail = fetched.stderr.strip().splitlines()
                return {
                    "state": "offline",
                    "repo": str(repo),
                    "head": head,
                    "dirty": dirty,
                    "detail": detail[-1] if detail else "",
                }

        commits = _git(repo, "log", "--format=%h %s", f"HEAD..{upstream_ref}").stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": "error", "detail": str(exc)}

    return {
        "state": "available" if commits else "current",
        "repo": str(repo),
        "upstream": upstream_ref,
        "head": head,
        "dirty": dirty,
        "behind": len(commits),
        "commits": commits[:20],
    }


def _installed_extras() -> list[str]:
    """Reinstall the same optional dependencies the user already has.

    Passing a fixed extras list would drag multi-gigabyte packages onto an
    install that deliberately went without them.
    """
    extras = []
    if _has_module("faster_whisper") or _has_module("whisper"):
        extras.append("whisper")
    if _has_module("sounddevice"):
        extras.append("recording")
    if _has_module("nvidia.cublas"):
        extras.append("cuda")
    return extras


def _stream(command: list[str], cwd: Path) -> Iterator[str]:
    """Yield a command's output line by line; return its exit code."""
    yield "$ " + " ".join(command)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        yield str(exc)
        return 127
    for line in process.stdout:
        yield line.rstrip("\n")
    process.wait()
    return process.returncode


def apply_update() -> Iterator[str]:
    """Pull and reinstall, yielding the log as it happens.

    Refuses again on its own rather than trusting the caller to have checked:
    this ends up behind an HTTP route, and the route is the only thing between
    a stray request and a `pip install`.
    """
    status = check_update()
    if status["state"] == "manual":
        yield "Aparté does not run from a git checkout — update it manually."
        return
    if status["state"] == "no_upstream":
        yield f"Branch {status.get('branch', '?')} tracks no remote branch — nothing to pull."
        return
    if status["state"] == "error":
        yield f"Cannot read the checkout: {status.get('detail', '')}"
        return
    if status.get("dirty"):
        yield "The checkout has uncommitted changes — commit or stash them first."
        yield "Pulling now would set them aside, and git does not always put them back."
        return

    repo = Path(status["repo"])
    if (yield from _stream(["git", "-C", str(repo), "pull", "--ff-only"], repo)) != 0:
        yield "Stopped: git pull failed. Nothing was installed."
        return

    extras = _installed_extras()
    target = f".[{','.join(extras)}]" if extras else "."
    if (yield from _stream([sys.executable, "-m", "pip", "install", "-e", target], repo)) != 0:
        yield "Stopped: pip install failed. The code was pulled but not installed."
        return

    yield DONE_MARKER


def restart() -> None:
    """Replace this process with a fresh one, running the code we just pulled.

    The server has the old modules loaded, so it cannot serve the update it just
    installed. Launched as `python -m aparte`, argv[0] is a file inside the
    package and re-running it directly would break the relative imports.
    """
    if Path(sys.argv[0]).name == "__main__.py":
        os.execv(sys.executable, [sys.executable, "-m", "aparte", *sys.argv[1:]])
    os.execv(sys.executable, [sys.executable, *sys.argv])
