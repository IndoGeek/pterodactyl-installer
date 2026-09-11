"""Package (apt) helpers and the installer's system dependencies."""
from __future__ import annotations

import subprocess
import sys

from .ui import say
from .utils import capture, installed, run

# Tracks every package this installer adds, for the uninstall manifest.
INSTALLED_BY_INSTALLER: list = []


def package_installed(package: str) -> bool:
    """Return whether dpkg considers a package installed (without apt work)."""
    return subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}', package],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True).stdout.strip() == 'installed'


def apt(*packages: str) -> None:
    """Install only missing packages, so rerunning the installer is safe and quick."""
    missing = [package for package in packages if not package_installed(package)]
    if not missing:
        say('All required system packages are already installed.')
        return
    say('Installing missing packages: ' + ', '.join(missing))
    run('apt-get', 'update')
    run('apt-get', 'install', '-y', *missing)
    for package in missing:
        if package not in INSTALLED_BY_INSTALLER:
            INSTALLED_BY_INSTALLER.append(package)


def install_panel_dependencies(webserver: str, php_version: str) -> None:
    packages = ['curl', 'tar', 'unzip', 'git', 'ca-certificates', 'gnupg', 'redis-server', 'mariadb-server']
    apt(*packages)
    # Keep FPM, CLI, Composer and extensions on the selected supported version;
    # never install the distribution's unversioned PHP meta-packages.
    apt(*(f'php{php_version}-{extension}' for extension in
          ('common', 'cli', 'fpm', 'gd', 'mysql', 'mbstring', 'bcmath', 'xml', 'curl', 'zip')))
    php_bin = f'php{php_version}'
    if not installed('composer'):
        run('sh', '-c', f'curl -sS https://getcomposer.org/installer | {php_bin} -- --install-dir=/usr/local/bin --filename=composer')
    required_extensions = {'pdo_mysql', 'zip', 'SimpleXML', 'bcmath', 'dom'}
    available_extensions = set(capture(php_bin, '-m').splitlines())
    missing_extensions = required_extensions - available_extensions
    if missing_extensions:
        sys.exit('PHP extensions are still unavailable after installation: ' +
                 ', '.join(sorted(missing_extensions)) +
                 '. Resolve the PHP repository/package configuration, then rerun the installer.')
    run('systemctl', 'enable', '--now', 'mariadb', 'redis-server', f'php{php_version}-fpm')