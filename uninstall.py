#!/usr/bin/env python3
"""Interactive, selective cleanup for an IndoGeek Pterodactyl installation."""
from __future__ import annotations

import json, os, re, shutil, subprocess, sys
from pathlib import Path

MANIFEST = Path('/var/lib/pterodactyl-installer/manifest.json')
PANEL = Path('/var/www/pterodactyl')

def say(message: str, kind='INFO') -> None:
    print(f'[{kind}] {message}')

def confirm(question: str, default=False) -> bool:
    hint = 'Y/n' if default else 'y/N'
    answer = input(f'{question} [{hint}]: ').strip().lower()
    return answer in ({'y', 'yes', ''} if default else {'y', 'yes'})

def run(*command: str, check=False):
    say('$ ' + ' '.join(command), 'RUN')
    return subprocess.run(command, text=True, check=check)

def installed(package: str) -> bool:
    return subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}', package],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True).stdout.strip() == 'installed'

def detected_php_version() -> str | None:
    text = ''
    for path in (Path('/etc/nginx/sites-enabled/pterodactyl.conf'), Path('/etc/nginx/sites-available/pterodactyl.conf')):
        if path.exists():
            text += path.read_text(errors='ignore')
    matches = re.findall(r'php(\d+\.\d+)-fpm\.sock', text)
    if matches:
        return matches[0]
    for version in ('8.5', '8.4', '8.3', '8.2'):
        if shutil.which(f'php{version}'):
            return version
    return None

def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()

def show_and_confirm(label: str, items: list[str]) -> bool:
    if not items:
        say(f'No {label} found.')
        return False
    say(f'{label}:')
    for item in items:
        print(f'  - {item}')
    return confirm(f'Remove these {label.lower()}?', default=False)

def main() -> None:
    if os.geteuid() != 0:
        sys.exit('Run as root: sudo pterodactyl-uninstall.py')
    if not confirm('This selectively removes Pterodactyl components and may destroy data. Continue?', default=False):
        return
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
    else:
        say(f'{MANIFEST} is missing. Only detected paths will be offered; package ownership is unknown.', 'WARN')
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
        run('systemctl', 'disable', '--now', 'pteroq.service')
        remove_path(Path('/etc/systemd/system/pteroq.service'))

    if confirm('Stop and remove Wings, its service, config, and binary?', default=False):
        run('systemctl', 'disable', '--now', 'wings.service')
        remove_path(Path('/etc/systemd/system/wings.service'))
        remove_path(Path('/usr/local/bin/wings'))
        remove_path(Path('/etc/pterodactyl'))

    web_files = [p for p in manifest.get('files', []) if 'nginx' in p or 'apache2' in p]
    if show_and_confirm('generated web-server configuration files', web_files):
        for raw in web_files:
            path = Path(raw)
            if 'apache2/sites-available' in raw:
                run('a2dissite', path.name)
            remove_path(path)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        run('systemctl', 'reload', 'apache2')

    cron_files = [p for p in manifest.get('files', []) if '/cron' in p]
    if show_and_confirm('generated cron files', cron_files):
        for raw in cron_files:
            remove_path(Path(raw))

    if show_and_confirm('Panel files', [str(PANEL)] if PANEL.exists() else []):
        remove_path(PANEL)

    certificate_domains = [d for d in (manifest.get('panel_domain'), manifest.get('wing_domain')) if d]
    if certificate_domains and confirm('Remove Let\'s Encrypt certificates for: ' + ', '.join(certificate_domains) + '?', default=False):
        if shutil.which('certbot'):
            for domain in dict.fromkeys(certificate_domains):
                run('certbot', 'delete', '--cert-name', domain, '--non-interactive')
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

    docker_packages = [p for p in ('docker-ce', 'docker-ce-cli', 'containerd.io', 'docker-buildx-plugin', 'docker-compose-plugin') if installed(p)]
    if show_and_confirm('Docker packages', docker_packages):
        run('systemctl', 'disable', '--now', 'docker.service')
        run('apt-get', 'purge', '-y', *docker_packages, check=True)

    if shutil.which('docker') and confirm('Remove Pterodactyl-labelled Docker containers and networks?', default=False):
        containers = set(subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=io.pterodactyl.type=server'], stdout=subprocess.PIPE, text=True).stdout.split())
        containers.update(subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=io.pterodactyl.server'], stdout=subprocess.PIPE, text=True).stdout.split())
        if containers:
            run('docker', 'rm', '-f', *sorted(containers))
        networks = subprocess.run(['docker', 'network', 'ls', '-q', '--filter', 'name=pterodactyl'], stdout=subprocess.PIPE, text=True).stdout.split()
        if networks:
            run('docker', 'network', 'rm', *networks)

    if confirm('Remove the recorded uninstall manifest?', default=True):
        remove_path(MANIFEST)
    say('Selective uninstall finished. Review the commands above and check service/package status.', 'OK')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled; no rollback was attempted.')
        sys.exit(130)
