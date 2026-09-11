"""Persistence of the uninstall manifest; credentials are deliberately excluded."""
from __future__ import annotations

import json
import os

from . import config


def write_manifest(setup: dict, installed_packages: list) -> None:
    manifest = {
        'panel_domain': setup['panel_domain'], 'wing_domain': setup['wing_domain'],
        'web': setup['web'], 'php_version': setup['php_version'],
        'packages': sorted(set(installed_packages)),
        'database_name': setup['db']['name'], 'database_user': setup['db']['user'],
        'files': ['/etc/cron.d/pterodactyl', '/etc/systemd/system/pteroq.service',
                  '/etc/systemd/system/wings.service', '/etc/pterodactyl/config.yml',
                  '/etc/nginx/sites-available/pterodactyl.conf',
                  '/etc/nginx/sites-enabled/pterodactyl.conf',
                  '/etc/nginx/sites-available/pterodactyl-wings-acme.conf',
                  '/etc/nginx/sites-enabled/pterodactyl-wings-acme.conf',
                  '/etc/apache2/sites-available/pterodactyl.conf',
                  '/etc/apache2/sites-available/pterodactyl-wings-acme.conf',
                  '/etc/apache2/sites-enabled/pterodactyl.conf',
                  '/etc/apache2/sites-enabled/pterodactyl-wings-acme.conf'],
    }
    config.MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_FILE.write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(config.MANIFEST_FILE, 0o600)