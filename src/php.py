"""PHP version selection and socket detection."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from . import config
from .ui import say
from .utils import installed


def select_php_version() -> str:
    """Prefer an installed PHP version supported by the current Panel series."""
    for version in config.SUPPORTED_PHP_VERSIONS:
        if installed(f'php{version}'):
            say(f'Using installed, Pterodactyl-supported PHP {version}.')
            return version
    # Pterodactyl's official 1.12 requirements recommend 8.3.
    say('No supported PHP version found; PHP 8.3 will be installed.', 'NOTE')
    return '8.3'


def php_fpm_socket(version: str) -> str:
    socket = f'/run/php/php{version}-fpm.sock'
    if not Path(socket).exists():
        sys.exit(f'PHP-FPM socket {socket} was not found. Check the php{version}-fpm service.')
    return socket


def detected_php_version() -> str | None:
    text = ''
    for path in (Path('/etc/nginx/sites-enabled/pterodactyl.conf'),
                 Path('/etc/nginx/sites-available/pterodactyl.conf')):
        if path.exists():
            text += path.read_text(errors='ignore')
    matches = re.findall(r'php(\d+\.\d+)-fpm\.sock', text)
    if matches:
        return matches[0]
    for version in ('8.5', '8.4', '8.3', '8.2'):
        if shutil.which(f'php{version}'):
            return version
    return None