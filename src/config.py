"""Central path and constant configuration."""
from __future__ import annotations

from pathlib import Path

# Paths inside this project. The resume state and the uninstall manifest live in
# ./state and every run is logged into ./logs.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / 'state'
STATE_FILE = STATE_DIR / 'state.json'
MANIFEST_FILE = STATE_DIR / 'manifest.json'
LOG_DIR = PROJECT_ROOT / 'logs'

# Paths on the host that the installer configures.
PANEL = Path('/var/www/pterodactyl')
PANEL_ENV = PANEL / '.env'
WINGS_CONFIG = Path('/etc/pterodactyl/config.yml')

SUPPORTED_PHP_VERSIONS = ('8.3', '8.2')