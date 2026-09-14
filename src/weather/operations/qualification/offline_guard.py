"""Early Python guard for reviewed offline children, not a native-code sandbox.

Load by an independently pinned absolute filename before importing candidate
modules. The owning native process job, scrubbed environment and fixed command
plan remain mandatory. Audit hooks do not constrain arbitrary native code.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _path(value):
    if isinstance(value, int) or value is None:
        return None
    return os.path.normcase(os.path.realpath(os.fsdecode(value)))


def _inside(value, roots):
    try:
        return any(os.path.commonpath((value, root)) == root for root in roots)
    except ValueError:
        return False


def install(*, writable_roots, forbidden_roots, executable_paths):
    """Deny ambient network, credential reads and writes outside scratch.

    A trusted caller chooses these roots/tools. This function never accepts an
    environment variable as approval and never changes ACLs or machine policy.
    """
    writable = tuple(_path(p) for p in writable_roots)
    forbidden = tuple(_path(p) for p in forbidden_roots)
    executables = frozenset(_path(p) for p in executable_paths)
    if not writable or any(not Path(p).is_absolute() for p in (*writable_roots, *forbidden_roots, *executable_paths)):
        raise ValueError("explicit absolute offline roots/tools required")
    if any(_inside(a, forbidden) or _inside(b, writable) for a in writable for b in forbidden):
        raise ValueError("offline writable and forbidden roots overlap")

    def check(value, *, write=False):
        path = _path(value)
        if path is not None and (_inside(path, forbidden) or (write and not _inside(path, writable))):
            raise PermissionError("qualification offline file access refused")

    def guard(event, args):
        if event in {"socket.connect", "socket.connect_ex", "socket.bind", "socket.getaddrinfo",
                     "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg",
                     "os.system", "os.exec", "os.posix_spawn", "pty.spawn", "winreg.OpenKey",
                     "winreg.CreateKey", "winreg.SetValue", "winreg.DeleteKey"}:
            raise PermissionError("qualification offline external access refused")
        if event == "open":
            _, mode, flags = args
            write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            check(args[0], write=write or bool(mode and any(c in mode for c in "wax+")))
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
            check(args[0], write=True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            check(args[0], write=True)
            check(args[1], write=True)
        elif event in {"os.listdir", "os.scandir"}:
            check(args[0])
        elif event == "subprocess.Popen":
            executable, _, cwd, environment = args
            if _path(executable) not in executables:
                raise PermissionError("qualification requires an approved child executable and explicit environment")
            check(cwd)
            if any(key.upper().startswith(("GH_", "GITHUB_", "AWS_", "AZURE_", "OPENAI_"))
                   or any(part in key.upper() for part in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
                   for key in (os.environ if environment is None else environment)):
                raise PermissionError("qualification child environment contains credential authority")

    sys.addaudithook(guard)
