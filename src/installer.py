"""Interactive Pterodactyl Panel + Wings installer orchestration."""
from __future__ import annotations

import secrets
import sys

from . import config, log
from .art import ART
from .certbot import configure_ssl
from .database import create_database
from .firewall import firewall
from .manifest import write_manifest
from .node import provision_node
from .packages import INSTALLED_BY_INSTALLER, install_panel_dependencies
from .panel import panel_setup
from .php import select_php_version
from .state import clear_resume_state, complete_phase, load_state, save_state
from .summary import completion_summary
from .ui import ask, confirm, say
from .utils import root_and_platform
from .webserver import apply_ssl, selected_webserver, webserver_config
from .wings import docker_and_wings


def repair_ssl() -> None:
    """Re-enable HTTPS for the configured panel domain without re-running the install.

    A resumed installer run rewrites the panel site to plain HTTP and the ssl phase is
    already checkpointed, so normal resume skips it. This applies the HTTPS server block
    from the certificates that already exist on disk."""
    repair_log = log.setup_logging('repair-ssl')
    print(ART)
    say('Applying the existing Let\'s Encrypt certificate to the panel site.', 'NOTE')
    root_and_platform()
    state = load_state()
    setup = state['config']
    written = apply_ssl(setup['web'], setup['panel_domain'], setup.get('php_version', ''))
    if not written:
        sys.exit(f'No certificate found at /etc/letsencrypt/live/{setup["panel_domain"]}; cannot enable HTTPS.')
    say(f'HTTPS enabled for https://{setup["panel_domain"]}. Open it in your browser to continue.', 'OK')
    say(f'Repair log: {repair_log}', 'OK')


def main() -> None:
    log_path = log.setup_logging('install')
    print(ART)
    say(f'Install log: {log_path}', 'NOTE')
    root_and_platform()
    say('This installer downloads official releases and changes system services, web-server config, MariaDB, Docker, and optionally UFW.', 'WARN')
    state = load_state()
    if state:
        say('Resuming the interrupted installation. Completed phases: ' +
            (', '.join(state['completed']) or 'none'), 'NOTE')
    else:
        if not confirm('Continue?'):
            return
        panel_domain = ask('Panel FQDN (e.g. panel.example.com)')
        wing_domain = ask('Wings FQDN (leave blank to reuse Panel FQDN)', required=False) or panel_domain
        wings_port = ask('Wings API port', '8080')
        wings_sftp = ask('Wings SFTP port', '2022')
        web = selected_webserver()
        php_version = select_php_version()
        db = {'name': ask('Database name', 'panel'), 'user': ask('Database user', 'pterodactyl'),
              'password': ask('Database password', secrets.token_urlsafe(24), secret=True)}
        admin = {'email': ask('Administrator email'), 'username': ask('Administrator username', 'admin'),
                 'first': ask('Administrator first name', 'Admin'), 'last': ask('Administrator last name', 'User'),
                 'password': ask('Administrator password', secret=True)}
        if confirm('Configure an SMTP mail server now?', default=False):
            say('Use SMTP credentials from your mail provider. They are stored in the Panel .env file.', 'NOTE')
            mail = {'driver': 'smtp', 'host': ask('SMTP host'), 'port': ask('SMTP port', '587'),
                    'username': ask('SMTP username', required=False), 'password': ask('SMTP password', secret=True, required=False),
                    'encryption': ask('SMTP encryption (tls/ssl/blank)', 'tls', required=False),
                    'from_address': ask('Mail from address', admin['email']), 'from_name': ask('Mail from name', 'Pterodactyl')}
        else:
            mail = {'driver': 'log', 'host': '', 'port': '', 'username': '', 'password': '', 'encryption': '',
                    'from_address': admin['email'], 'from_name': 'Pterodactyl'}
        state = {'config': {'panel_domain': panel_domain, 'wing_domain': wing_domain,
                            'wings_port': wings_port, 'wings_sftp': wings_sftp, 'web': web, 'php_version': php_version,
                            'db': db, 'admin': admin, 'mail': mail}, 'completed': []}
        save_state(state)
        say(f'Resume state saved to {config.STATE_FILE} (root-only).', 'NOTE')

    setup = state['config']
    completed = state['completed']
    # Resume states written by older installer versions did not pin PHP.
    if 'php_version' not in setup:
        setup['php_version'] = select_php_version()
        save_state(state)
    panel_domain, wing_domain = setup['panel_domain'], setup['wing_domain']
    if wing_domain == panel_domain:
        say('Wings shares the panel FQDN. Disable Cloudflare proxying (orange cloud) for Wings traffic.', 'WARN')
    if 'dependencies' not in completed:
        install_panel_dependencies(setup['web'], setup['php_version'])
        complete_phase(state, 'dependencies')
    if 'database' not in completed:
        create_database(**setup['db'])
        complete_phase(state, 'database')
    if 'panel' not in completed:
        # Panel setup was not completed (crashed during account creation, or the checkpoint
        # was edited). Reconfirm the administrator so a stale account can be replaced.
        say('Resuming with an unfinished Panel phase; please reconfirm the administrator account.', 'NOTE')
        current = setup['admin']
        setup['admin'] = {'email': ask('Administrator email', current['email']),
                          'username': ask('Administrator username', current['username']),
                          'first': ask('Administrator first name', current['first']),
                          'last': ask('Administrator last name', current['last']),
                          'password': ask('Administrator password', secret=True)}
        if setup['mail']['from_address'] == current['email'] and setup['mail']['from_address'] != setup['admin']['email']:
            setup['mail']['from_address'] = setup['admin']['email']
        save_state(state)
        panel_setup(panel_domain, setup['db'], setup['admin'], setup['mail'], setup['php_version'])
        complete_phase(state, 'panel')
    if 'webserver' not in completed:
        webserver_config(setup['web'], panel_domain, setup['php_version'])
        complete_phase(state, 'webserver')
    if 'ssl' not in completed:
        configure_ssl(setup['web'], panel_domain, wing_domain, setup['admin']['email'], setup['php_version'])
        complete_phase(state, 'ssl')
    if 'wings' not in completed:
        docker_and_wings()
        complete_phase(state, 'wings')
    if 'firewall' not in completed:
        setup['unopened_ports'] = firewall(setup['wings_port'], setup['wings_sftp'])
        save_state(state)
        complete_phase(state, 'firewall')
    if 'node' not in completed:
        if confirm('Create the Panel node through the supported Application API and start Wings now?', default=True):
            provision_node(panel_domain, wing_domain, setup['admin']['email'], setup['wings_port'], setup['wings_sftp'])
        else:
            say('Wings binary and service are installed but not started. Add a node in the panel, save its config to /etc/pterodactyl/config.yml, then run: systemctl enable --now wings', 'WARN')
        complete_phase(state, 'node')
    if setup.get('unopened_ports'):
        say('You chose not to open these TCP ports in UFW: %s. Open any that this server needs before using the Panel/Wings.' % ', '.join(setup['unopened_ports']), 'WARN')
    say('Also open every game-server allocation port you add in the Panel; those ports are intentionally not managed automatically.', 'WARN')
    completion_summary(setup)
    say('Installation completed. Save the APP_KEY securely: grep APP_KEY /var/www/pterodactyl/.env', 'OK')
    write_manifest(setup, INSTALLED_BY_INSTALLER)
    clear_resume_state()
    say(f'Full install log: {log_path}', 'OK')