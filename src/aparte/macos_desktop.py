"""macOS application bundle (M7) — everything decidable, decided here.

On Mac the permission dialogs today say *Terminal*, because Terminal is what launches
Python, and TCC attributes a request to the **responsible** process — the bundle
LaunchServices started. Wrapping Aparté in a real ``.app`` is what makes them say
*Aparté* instead. That is the whole point of this module.

**The main executable is a Mach-O binary, never a script.** Apple DTS is explicit
(developer.apple.com/forums/thread/678819): *"TCC expects its bundled clients … to use a
native main executable. … If your product uses a script as its main executable, you're
likely to encounter TCC problems."* So :func:`launcher_source` emits a small C program,
compiled on the user's machine by the Homebrew formula with the command-line tools
Homebrew already requires. Nothing here is downloaded as an application, so nothing is
ever quarantined and Gatekeeper has nothing to examine.

**The bundle must not change between two versions of Aparté.** An ad-hoc signature has no
team identity: the requirement TCC stores is pinned to the code's ``cdhash``. If the
bundle changes, macOS forgets the permissions — *and the checkbox stays ticked in System
Settings*, so the failure is silent. Hence: no Aparté version in the bundle, no Python
code in the bundle, and the interpreter named through Homebrew's version-stable ``opt``
path rather than the ``Cellar`` path that moves on every upgrade. ``brew upgrade``
replaces the prefix and never touches the bundle.

Everything in this module is pure string and path work, so it is proved on the Linux dev
machine. What cannot be proved here — LaunchServices, ``codesign``, and the TCC
attribution itself — is measured on a real Mac by the M7-0 probe.
"""

from __future__ import annotations

import plistlib
import shutil
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

BUNDLE_NAME = "Aparté.app"
BUNDLE_IDENTIFIER = "ca.collectifweb.aparte"
LAUNCHER_NAME = "aparte"
ICON_FILE = "aparte.icns"

# The launcher's own version, deliberately NOT Aparté's. Bumping it would change the
# bundle, hence the cdhash, hence every granted permission (see the module docstring).
# It moves only when the launcher itself changes, which is a decision, never a release.
LAUNCHER_VERSION = "1.0"

# How the launcher hands over to Python. Which one keeps the TCC attribution is measured
# by M7-0 on a real Mac, not argued here: EXEC replaces the process image, so the
# bundle's main executable no longer exists; CHILD keeps it alive as the parent, which is
# the unambiguous case but costs signal forwarding.
LAUNCH_EXEC = "exec"
LAUNCH_CHILD = "child"

# Fixed compile options. Determinism is what protects the granted permissions, so nothing
# here may vary with the clock, the build directory, or the machine's SDK default:
# -O2 with no debug info leaves no temporary paths in the binary, and the deployment
# target is pinned rather than inherited. Big Sur is the floor M8 validated on.
MACOSX_DEPLOYMENT_TARGET = "11.0"
CLANG_OPTIONS = (
    "-O2",
    "-g0",
    "-fno-common",
    f"-mmacosx-version-min={MACOSX_DEPLOYMENT_TARGET}",
)


def applications_dir() -> Path:
    """Where the bundle lives: the user's own Applications folder.

    ``~/Applications`` rather than ``/Applications``: no administrator rights, and
    Finder, Spotlight and Launchpad all index it. It sits **outside** the Homebrew
    prefix on purpose — a prefix bundle would be rebuilt by every ``brew upgrade``, and
    a rebuilt bundle is a new cdhash, i.e. permissions lost.
    """
    return Path.home() / "Applications"


def bundle_path() -> Path:
    return applications_dir() / BUNDLE_NAME


def stable_interpreter(executable: str) -> str:
    """Rewrite a Homebrew ``Cellar`` interpreter path to its version-stable ``opt`` twin.

    ``sys.executable`` points into the versioned cellar
    (``/opt/homebrew/Cellar/aparte/1.1.1/libexec/bin/python3``), which disappears at the
    first ``brew upgrade`` — the launcher would then name a path that no longer exists.
    Homebrew keeps ``/opt/homebrew/opt/aparte/libexec/bin/python3`` pointing at the
    current version, so that is what gets baked in.

    Anything that is not a cellar path is returned untouched: a plain virtualenv, a
    system interpreter, or a checkout used by a tester.
    """
    parts = Path(executable).parts
    try:
        cellar = parts.index("Cellar")
    except ValueError:
        return executable
    # …/Cellar/<formula>/<version>/rest… → …/opt/<formula>/rest…
    if len(parts) < cellar + 3:
        return executable
    formula = parts[cellar + 1]
    rest = parts[cellar + 3 :]
    return str(Path(*parts[:cellar], "opt", formula, *rest))


# Shown by macOS inside its own "Aparté would like to access the microphone" dialog. The
# system draws it, so it has to be a plain sentence, in the user's language.
MICROPHONE_REASON = {
    "fr": "Aparté transcrit votre voix sur votre Mac. Rien n'est envoyé sur Internet.",
    "en": "Aparté transcribes your voice on your Mac. Nothing is sent to the internet.",
}

# Shown by the launcher itself when the interpreter is gone — a .app that dies from
# Finder leaves no trace at all, no terminal and no message.
MISSING_INTERPRETER_MESSAGE = {
    "fr": (
        "Aparté ne trouve plus son moteur.\\n\\n"
        "Réinstalle-le, puis relance :\\n"
        "brew install collectifweb/aparte/aparte\\n"
        "aparte install-app --force"
    ),
    "en": (
        "Aparté can no longer find its engine.\\n\\n"
        "Reinstall it, then run:\\n"
        "brew install collectifweb/aparte/aparte\\n"
        "aparte install-app --force"
    ),
}


def build_info_plist(language: str | None = None) -> bytes:
    """The bundle's ``Info.plist``, as bytes ready to write.

    Deliberately free of anything that moves between Aparté releases — see the module
    docstring. ``language`` remains accepted for older probe scripts, but cannot
    change the signed bytes: macOS chooses from the bundled localizations.
    """
    document = {
        "CFBundleDevelopmentRegion": "fr",
        "CFBundleLocalizations": ["fr", "en"],
        "CFBundleDisplayName": "Aparté",
        "CFBundleExecutable": LAUNCHER_NAME,
        "CFBundleIconFile": ICON_FILE,
        # Definitive. Changing it after release would be a second application in TCC's
        # eyes, and the user would have to grant everything again without understanding.
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Aparté",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": LAUNCHER_VERSION,
        "CFBundleVersion": LAUNCHER_VERSION,
        # No Dock icon and no menu bar: Aparté lives in the menu-bar icon built in M6.
        "LSUIElement": True,
        "LSMinimumSystemVersion": MACOSX_DEPLOYMENT_TARGET,
        # Without this key macOS kills the process instead of asking for the microphone.
        "NSMicrophoneUsageDescription": MICROPHONE_REASON["fr"],
    }
    return plistlib.dumps(document, fmt=plistlib.FMT_XML, sort_keys=False)


def _c_string(text: str) -> str:
    """Quote a Python string as a C string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# What the launcher runs. The M7-0 probe passes its own arguments; everything else uses
# this default, which is the resident server the menu-bar icon and the shortcut live in.
DEFAULT_ARGS = ("-m", "aparte", "desktop")


def launcher_source(
    interpreter: str,
    mode: str = LAUNCH_EXEC,
    language: str | None = None,
    args: tuple[str, ...] = DEFAULT_ARGS,
) -> str:
    """The C source of the bundle's main executable.

    Kept to one file with no configuration of its own: everything it needs is baked in
    at generation time, so the compiled binary is a pure function of this text and the
    fixed compile options — which is what keeps the cdhash, and the permissions, stable.

    ``mode`` picks how it hands over to Python (:data:`LAUNCH_EXEC` or
    :data:`LAUNCH_CHILD`); M7-0 measures which one macOS keeps attributing to the bundle.
    """
    if mode not in (LAUNCH_EXEC, LAUNCH_CHILD):
        raise ValueError(f"unknown launch mode: {mode!r}")
    child = mode == LAUNCH_CHILD
    baked = "".join(f"    {_c_string(arg)},\n" for arg in args)
    return _LAUNCHER_TEMPLATE.format(
        interpreter=_c_string(interpreter),
        message=_c_string(MISSING_INTERPRETER_MESSAGE["fr"] + "\\n\\n"
                          + MISSING_INTERPRETER_MESSAGE["en"]),
        arguments=baked,
        helpers=_CHILD_HELPERS if child else "",
        handover=_CHILD_HANDOVER if child else _EXEC_HANDOVER,
    )


# Replaces this process with Python: one process, nothing to forward. Whether the bundle
# stays the responsible process once its own image is gone is exactly the M7-0 question.
_EXEC_HANDOVER = """\
    execv(kInterpreter, argv_out);
    /* Only reached when execv itself failed. */
    show_error();
    return 1;
"""

# Emitted only in child mode: in exec mode the process is gone before any signal could
# be forwarded, and an unused static function is a warning on every compile.
_CHILD_HELPERS = """\

static pid_t g_child = 0;

static void forward_signal(int signum) {
    if (g_child > 0) {
        kill(g_child, signum);
    }
}
"""

# Keeps the bundle's own executable alive as the parent, so a process whose main
# executable really is inside the bundle exists for as long as Aparté runs. Costs signal
# forwarding and exit-code propagation.
_CHILD_HANDOVER = """\
    pid_t child = 0;
    if (posix_spawn(&child, kInterpreter, NULL, NULL, argv_out, environ) != 0) {
        show_error();
        return 1;
    }
    g_child = child;
    signal(SIGTERM, forward_signal);
    signal(SIGINT, forward_signal);
    int status = 0;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
        /* A forwarded signal interrupts the wait; keep waiting. */
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
"""


_LAUNCHER_TEMPLATE = """\
/* Aparté — bundle launcher. Generated by aparte.macos_desktop; do not edit by hand.
 *
 * Exists for one reason: macOS attributes a permission request to the responsible
 * process, and Apple requires an app bundle's main executable to be Mach-O rather than
 * a script. Without this binary the microphone and Accessibility dialogs name Terminal.
 *
 * It stays deliberately dumb — resolve, check, hand over — because every byte of it is
 * part of the code identity that TCC pins the granted permissions to.
 */
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static const char *kInterpreter = {interpreter};
static const char *kMessage = {message};

/* Baked in at generation time, so the binary is a pure function of this source. */
static const char *kArguments[] = {{
{arguments}}};
static const int kArgumentCount = (int)(sizeof(kArguments) / sizeof(kArguments[0]));
{helpers}
/* Say something when the engine is gone. A bundle launched from Finder that just dies
 * leaves nothing behind: no terminal, no message, no way for the user to know why. */
static void show_error(void) {{
    char script[2048];
    snprintf(script, sizeof(script),
             "display dialog \\"%s\\" with title \\"Aparté\\" "
             "buttons {{\\"OK\\"}} default button 1 with icon caution",
             kMessage);
    char *const args[] = {{"osascript", "-e", script, NULL}};
    pid_t pid = 0;
    if (posix_spawn(&pid, "/usr/bin/osascript", NULL, NULL, args, environ) == 0) {{
        int ignored = 0;
        waitpid(pid, &ignored, 0);
    }}
}}

int main(int argc, char *argv[]) {{
    struct stat info;
    if (stat(kInterpreter, &info) != 0) {{
        show_error();
        return 1;
    }}

    /* The baked arguments, plus whatever we were opened with. */
    char **argv_out = calloc((size_t)argc + (size_t)kArgumentCount + 2, sizeof(char *));
    if (argv_out == NULL) {{
        return 1;
    }}
    int n = 0;
    argv_out[n++] = (char *)kInterpreter;
    for (int i = 0; i < kArgumentCount; i++) {{
        argv_out[n++] = (char *)kArguments[i];
    }}
    for (int i = 1; i < argc; i++) {{
        argv_out[n++] = argv[i];
    }}
    argv_out[n] = NULL;

{handover}}}
"""


def clang_command(source: Path, output: Path) -> list[str]:
    """The compile command, with every option fixed.

    Nothing here may depend on the clock or on where the build happened: the linker
    derives its UUID from the content, so identical input gives an identical binary,
    which is what lets a reinstall keep the granted permissions.
    """
    return ["clang", *CLANG_OPTIONS, "-o", str(output), str(source)]


def codesign_command(bundle: Path) -> list[str]:
    """Ad-hoc signature. Required, never best-effort.

    A bundle that is unsigned or badly signed must not be reported as installed — and
    Apple Silicon refuses to run unsigned native code at all. ``--force`` replaces any
    signature already there; the identifier is pinned so it never gets guessed from the
    file name.
    """
    return [
        "codesign",
        "--force",
        "--sign",
        "-",
        "--identifier",
        BUNDLE_IDENTIFIER,
        str(bundle),
    ]


def write_bundle(destination: Path, interpreter: str, *, mode: str = LAUNCH_EXEC,
                 language: str | None = None,
                 args: tuple[str, ...] = DEFAULT_ARGS) -> dict[str, Path]:
    """Lay out the bundle's non-compiled parts and the launcher source.

    Returns the paths the caller needs to finish the job: compile the source into
    ``executable``, then sign ``destination``. Splitting it this way keeps everything
    that can be proved on Linux — the tree, the plist, the C source — apart from the two
    steps that need a Mac.
    """
    contents = destination / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    plist = contents / "Info.plist"
    plist.write_bytes(build_info_plist(language))

    # Both localizations ship on every machine. Choosing one while building
    # would change the signed identity when the shell locale changes.
    for locale, reason in MICROPHONE_REASON.items():
        localized = resources / f"{locale}.lproj" / "InfoPlist.strings"
        localized.parent.mkdir(parents=True, exist_ok=True)
        localized.write_bytes(plistlib.dumps({
            "CFBundleDisplayName": "Aparté",
            "NSMicrophoneUsageDescription": reason,
        }, fmt=plistlib.FMT_XML, sort_keys=True))

    source = contents / f"{LAUNCHER_NAME}.c"
    source.write_text(
        launcher_source(interpreter, mode=mode, language=language, args=args), encoding="utf-8"
    )

    icon = ASSETS_DIR / ICON_FILE
    installed_icon = resources / ICON_FILE
    if icon.exists():
        shutil.copyfile(icon, installed_icon)

    return {
        "bundle": destination,
        "plist": plist,
        "source": source,
        "executable": macos / LAUNCHER_NAME,
        "icon": installed_icon,
    }
