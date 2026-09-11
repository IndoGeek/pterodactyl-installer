"""Panel extraction, .env writing, scheduler and the pteroq service."""
from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

from . import config
from .ui import say
from .utils import run


def write_env(values: dict) -> None:
    raw = (config.PANEL / '.env.example').read_text()
    for key, value in values.items():
        raw = re.sub(rf'^{re.escape(key)}=.*$', f'{key}={value}', raw, flags=re.M)
    config.PANEL_ENV.write_text(raw)
    os.chmod(config.PANEL_ENV, 0o640)


def write_scheduler(php_version: str) -> None:
    # /etc/cron.d requires a user field; this is the system-cron equivalent of
    # Pterodactyl's official every-minute schedule:run entry.
    Path('/etc/cron.d/pterodactyl').write_text(
        f'* * * * * www-data /usr/bin/php{php_version} /var/www/pterodactyl/artisan schedule:run >> /dev/null 2>&1\n')


def panel_setup(domain: str, db: dict, admin: dict, mail: dict, php_version: str) -> None:
    # A prior interrupted installer run may already have extracted the release.
    # Only reject an unrelated directory; continue safely from an extracted panel.
    if config.PANEL.exists() and any(config.PANEL.iterdir()) and not (config.PANEL / '.env.example').exists():
        sys.exit(f'{config.PANEL} is not a recognizable panel installation. Refusing to overwrite it.')
    # This also handles installations interrupted after pteroq was enabled.
    prepared_panel = config.PANEL_ENV.exists() and (config.PANEL / 'vendor/autoload.php').exists() and Path('/etc/systemd/system/pteroq.service').exists()
    if prepared_panel:
        say('Existing prepared Panel detected; preserving its .env and administrator account.')
        write_scheduler(php_version)
        return
    config.PANEL.mkdir(parents=True, exist_ok=True)
    if not (config.PANEL / '.env.example').exists():
        run('curl', '-fL', '-o', 'panel.tar.gz', 'https://github.com/pterodactyl/panel/releases/latest/download/panel.tar.gz', cwd=config.PANEL)
        run('tar', '-xzf', 'panel.tar.gz', cwd=config.PANEL)
        (config.PANEL / 'panel.tar.gz').unlink(missing_ok=True)
    write_env({'APP_ENV': 'production', 'APP_DEBUG': 'false', 'APP_URL': f'https://{domain}',
               'DB_HOST': '127.0.0.1', 'DB_PORT': '3306', 'DB_DATABASE': db['name'], 'DB_USERNAME': db['user'],
               'DB_PASSWORD': db['password'], 'CACHE_DRIVER': 'redis', 'SESSION_DRIVER': 'redis', 'QUEUE_CONNECTION': 'redis',
               'MAIL_MAILER': mail['driver'], 'MAIL_HOST': mail['host'], 'MAIL_PORT': mail['port'],
               'MAIL_USERNAME': mail['username'], 'MAIL_PASSWORD': mail['password'],
               'MAIL_ENCRYPTION': mail['encryption'], 'MAIL_FROM_ADDRESS': mail['from_address'], 'MAIL_FROM_NAME': mail['from_name']})
    env = os.environ.copy()
    env['COMPOSER_ALLOW_SUPERUSER'] = '1'
    php_bin = f'php{php_version}'
    run(php_bin, '/usr/local/bin/composer', 'install', '--no-dev', '--optimize-autoloader', cwd=config.PANEL, env=env)
    run(php_bin, 'artisan', 'key:generate', '--force', cwd=config.PANEL)
    run(php_bin, 'artisan', 'migrate', '--seed', '--force', cwd=config.PANEL)
    # The command's non-interactive flags avoid recording the password in shell history.
    run(php_bin, 'artisan', 'p:user:make', '--email', admin['email'], '--username', admin['username'],
        '--name-first', admin['first'], '--name-last', admin['last'], '--password', admin['password'],
        '--admin', '1', cwd=config.PANEL)
    run('chown', '-R', 'www-data:www-data', str(config.PANEL))
    run('chmod', '-R', '755', str(config.PANEL / 'storage'), str(config.PANEL / 'bootstrap/cache'))
    write_scheduler(php_version)
    Path('/etc/systemd/system/pteroq.service').write_text(textwrap.dedent('''\
        [Unit]
        Description=Pterodactyl Queue Worker
        After=redis-server.service
        [Service]
        User=www-data
        Group=www-data
        Restart=always
        ExecStart=/usr/bin/php /var/www/pterodactyl/artisan queue:work --queue=high,standard,low --sleep=3 --tries=3
        [Install]
        WantedBy=multi-user.target
    '''))
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'pteroq')