"""Interactive, selective cleanup for an IndoGeek Pterodactyl installation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, log
from .packages import installed
from .php import detected_php_version
from .ui import confirm, say, show_and_confirm
from .utils import remove_path, run


def main() -> None:
    log_path = log.setup_logging('uninstall')
    say(f'Uninstall log: {log_path}', 'NOTE')
    if os.geteuid() != 0:
        sys.exit('Run as root: sudo uninstall.sh')
    if not confirm('This selectively removes Pterodactyl components and may destroy data. Continue?', default=False):
        return
    if config.MANIFEST_FILE.exists():
        manifest = json.loads(config.MANIFEST_FILE.read_text())
    else:
        say(f'{config.MANIFEST_FILE} is missing. Only detected paths will be offered; package ownership is unknown.', 'WARN')
        manifest = {'packages': [], 'files': [], 'php_version': None,
                    'panel_domain': '', 'wing_domain': '', 'database_name': '', 'database_user': ''}
        manifest['php_version'] = detected_php_version()
        if manifest['php_version']:
            say(f'Detected PHP {manifest["php_version"]} from the existing Panel configuration.', 'NOTE')
            all_packages = subprocess.run(['dpkg-query', '-W', '-f=${binary:Package}\n'],
                                          stdout=subprocess.PIPE, text=True).stdout.splitlines()
            manifest['packages'] = [p for p in all_packages if p.startswith(f"php{manifest['php_version']}")]

    # Stop services first, but only when the user approves that service group.
    if confirm('Stop and remove the Pterodactyl queue worker (pteroq)?', default=False):
        run('systemctl', 'disable', '--now', 'pteroq.service', check=False)
        remove_path(Path('/etc/systemd/system/pteroq.service'))

    if confirm('Stop and remove Wings, its service, config, and binary?', default=False):
        run('systemctl', 'disable', '--now', 'wings.service', check=False)
        remove_path(Path('/etc/systemd/system/wings.service'))
        remove_path(Path('/usr/local/bin/wings'))
        remove_path(Path('/etc/pterodactyl'))

    web_files = [p for p in manifest.get('files', []) if 'nginx' in p or 'apache2' in p]
    if show_and_confirm('generated web-server configuration files', web_files):
        for raw in web_files:
            path = Path(raw)
            if 'apache2/sites-available' in raw:
                run('a2dissite', path.name, check=False)
            remove_path(path)
        run('nginx', '-t', check=False)
        run('systemctl', 'reload', 'nginx', check=False)
        run('systemctl', 'reload', 'apache2', check=False)

    cron_files = [p for p in manifest.get('files', []) if '/cron' in p]
    if show_and_confirm('generated cron files', cron_files):
        for raw in cron_files:
            remove_path(Path(raw))

    if show_and_confirm('Panel files', [str(config.PANEL)] if config.PANEL.exists() else []):
        remove_path(config.PANEL)

    certificate_domains = [d for d in (manifest.get('panel_domain'), manifest.get('wing_domain')) if d]
    if certificate_domains and confirm('Remove Let\'s Encrypt certificates for: ' + ', '.join(certificate_domains) + '?', default=False):
        if shutil.which('certbot'):
            for domain in dict.fromkeys(certificate_domains):
                run('certbot', 'delete', '--cert-name', domain, '--non-interactive', check=False)
        else:
            say('certbot is not installed; certificate files were left untouched.', 'WARN')

    database = manifest.get('database_name')
    db_user = manifest.get('database_user')
    if database and confirm(f'Drop MariaDB database `{database}` and user `{db_user}`?', default=False):
        safe_db = database.replace('`', '``')
        safe_user = (db_user or '').replace("'", "''")
        sql = f"DROP DATABASE IF EXISTS `{safe_db}`; DROP USER IF EXISTS '{safe_user}'@'127.0.0.1'; FLUSH PRIVILEGES;"
        run('mariadb', '-e', sql, check=True)

    php_version = manifest.get('php_version')
    php_packages = [p for p in manifest.get('packages', []) if php_version and p.startswith(f'php{php_version}')]
    if show_and_confirm(f'PHP {php_version} packages installed by this installer', php_packages):
        run('apt-get', 'purge', '-y', *php_packages, check=True)

    other_packages = [p for p in manifest.get('packages', []) if p not in php_packages]
    if show_and_confirm('other packages installed by this installer', other_packages):
        installed_packages = [p for p in other_packages if installed(p)]
        if installed_packages:
            run('apt-get', 'purge', '-y', *installed_packages, check=True)

    if confirm('Remove the Composer binary installed at /usr/local/bin/composer?', default=False):
        remove_path(Path('/usr/local/bin/composer'))

    docker_packages = [p for p in ('docker-ce', 'docker-ce-cli', 'containerd.io',
                                   'docker-buildx-plugin', 'docker-compose-plugin') if installed(p)]
    if show_and_confirm('Docker packages', docker_packages):
        run('systemctl', 'disable', '--now', 'docker.service', check=False)
        run('apt-get', 'purge', '-y', *docker_packages, check=True)

    if shutil.which('docker') and confirm('Remove Pterodactyl-labelled Docker containers and networks?', default=False):
        containers = set(subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=io.pterodactyl.type=server'],
                                        stdout=subprocess.PIPE, text=True).stdout.split())
        containers.update(subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=io.pterodactyl.server'],
                                         stdout=subprocess.PIPE, text=True).stdout.split())
        if containers:
            run('docker', 'rm', '-f', *sorted(containers))
        networks = subprocess.run(['docker', 'network', 'ls', '-q', '--filter', 'name=pterodactyl'],
                                  stdout=subprocess.PIPE, text=True).stdout.split()
        if networks:
            run('docker', 'network', 'rm', *networks)

    if confirm('Remove the recorded uninstall manifest?', default=True):
        remove_path(config.MANIFEST_FILE)
    say('Selective uninstall finished. Review the commands above and check service/package status.', 'OK')
    say(f'Full uninstall log: {log_path}', 'OK')