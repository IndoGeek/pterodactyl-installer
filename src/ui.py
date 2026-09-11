"""Console interaction helpers that also mirror output to the log file."""
from __future__ import annotations

import getpass

from . import log


def say(message: str, kind: str = 'INFO') -> None:
    print(f'[{kind}] {message}')
    log.record(kind, f'[{kind}] {message}')


def ask(label: str, default: str | None = None, secret: bool = False, required: bool = True) -> str:
    suffix = f' [{default}]' if default else ''
    while True:
        value = (getpass.getpass if secret else input)(f'{label}{suffix}: ')
        value = value or (default or '')
        if value or not required:
            return value
        say('This value is required.', 'ERROR')


def confirm(question: str, default: bool = False) -> bool:
    hint = 'Y/n' if default else 'y/N'
    answer = input(f'{question} [{hint}]: ').strip().lower()
    return answer in ({'y', 'yes', ''} if default else {'y', 'yes'})


def show_and_confirm(label: str, items: list) -> bool:
    if not items:
        say(f'No {label} found.')
        return False
    say(f'{label}:')
    for item in items:
        print(f'  - {item}')
        log.record('INFO', f'  - {item}')
    return confirm(f'Remove these {label.lower()}?', default=False)