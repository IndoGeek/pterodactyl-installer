"""Generic helpers for running commands and checking the environment."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .ui import say


def run(*command: str, check: bool = True, cwd: Path | None = None, env=None) -> subprocess.CompletedProcess:
    printable = ' '.join(command)
    say(f'$ {printable}', 'RUN')
    return subprocess.run(command, check=check, cwd=cwd, env=env, text=True)


def capture(*command: str) -> str:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()


def installed(binary: str) -> bool:
    return shutil.which(binary) is not None


def root_and_platform() -> None:
    if os.geteuid() != 0:
        sys.exit('Run this installer as root: sudo python3 install.py')
    if not Path('/etc/debian_version').exists():
        sys.exit('This initial release supports Debian and Ubuntu only. No changes were made.')


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()