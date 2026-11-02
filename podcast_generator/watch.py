"""podcast_generator.watch: the `podcast-watch` command (Windows only).

    podcast-watch              open the Podcast Watch app
    podcast-watch --shortcut   put a "Podcast Watch" shortcut on the desktop

The app itself is podcast-watch.ps1, shipped inside this package. This
launcher tells it which Python environment to schedule (the one running
this command), where the home folder is, and the version for its About box.
"""

import os
import subprocess
import sys

from . import __version__
from .paths import PACKAGE_DIR, home_dir

SCRIPT = os.path.join(PACKAGE_DIR, "podcast-watch.ps1")
SHORTCUT_NAME = "Podcast Watch.lnk"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _pythonw() -> str:
    """pythonw.exe next to the running interpreter, so nothing flashes up."""
    exe_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(exe_dir, "pythonw.exe")
    return candidate if os.path.isfile(candidate) else sys.executable


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def open_app() -> int:
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", SCRIPT,
         "-PythonW", _pythonw(), "-HomeDir", home_dir(), "-Version", __version__],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
    )
    return 0


def make_shortcut() -> int:
    """Desktop shortcut that runs `pythonw -m podcast_generator.watch`."""
    pythonw = _pythonw()
    # WScript.Shell finds the real Desktop, including a OneDrive-redirected one.
    command = "; ".join([
        "$ErrorActionPreference = 'Stop'",
        "$wsh = New-Object -ComObject WScript.Shell",
        f"$path = Join-Path $wsh.SpecialFolders('Desktop') {_ps_quote(SHORTCUT_NAME)}",
        "$lnk = $wsh.CreateShortcut($path)",
        f"$lnk.TargetPath = {_ps_quote(pythonw)}",
        "$lnk.Arguments = '-m podcast_generator.watch'",
        f"$lnk.WorkingDirectory = {_ps_quote(home_dir())}",
        "$lnk.IconLocation = (Get-Command powershell.exe).Source + ',0'",
        "$lnk.Description = 'Turn the podcast_generator folder watch on or off'",
        "$lnk.Save()",
        "$path",
    ])
    os.makedirs(home_dir(), exist_ok=True)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        print(f"Couldn't create the shortcut: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"Created {result.stdout.strip()}")
    return 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.name != "nt":
        print("Podcast Watch is Windows-only (it manages a Windows scheduled "
              "task). On other systems, schedule `podcast-generator` with "
              "cron or similar.", file=sys.stderr)
        return 1
    if args in ([], ["--shortcut"]):
        return make_shortcut() if args else open_app()
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
