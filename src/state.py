"""Resume-state persistence for the installer."""
from __future__ import annotations

import json
import os
import sys

from . import config
from .ui import say


def save_state(state: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = config.STATE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(config.STATE_FILE)
    os.chmod(config.STATE_FILE, 0o600)


def load_state() -> dict | None:
    if not config.STATE_FILE.exists():
        return None
    try:
        state = json.loads(config.STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f'Cannot read installer resume state {config.STATE_FILE}: {exc}')
    if not isinstance(state, dict) or 'config' not in state or 'completed' not in state:
        sys.exit(f'Installer resume state {config.STATE_FILE} is invalid. Move it aside only if you intend to start over.')
    return state


def complete_phase(state: dict, phase: str) -> None:
    if phase not in state['completed']:
        state['completed'].append(phase)
    save_state(state)
    say(f'Checkpoint saved: {phase}', 'OK')


def clear_resume_state() -> None:
    """Remove the temporary resume files but keep the original state directory."""
    config.STATE_FILE.unlink(missing_ok=True)
    config.STATE_FILE.with_suffix('.tmp').unlink(missing_ok=True)