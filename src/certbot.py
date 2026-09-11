"""Let's Encrypt (Certbot) certificate handling for the Panel and Wings hostnames."""
from __future__ import annotations

from pathlib import Path

from .packages import apt
from .ui import confirm, say
from .utils import run
from .webserver import enable_acme_webroot_site


def configure_ssl(web: str, panel_domain: str, wing_domain: str, email: str) -> None:
    domains = list(dict.fromkeys([panel_domain, wing_domain]))
    missing = [d for d in domains if not Path(f'/etc/letsencrypt/live/{d}/fullchain.pem').exists()]
    if not missing:
        say('Existing Let\'s Encrypt certificate(s) found.')
        return
    if not confirm('Obtain missing Let\'s Encrypt certificates now? DNS must already point here.'):
        say('SSL skipped; panel APP_URL remains HTTPS and will not work until certificates/configuration are completed.', 'WARN')
        return
    apt('certbot', 'python3-certbot-nginx' if web == 'nginx' else 'python3-certbot-apache')
    if panel_domain in missing:
        run('certbot', '--nginx' if web == 'nginx' else '--apache', '--non-interactive', '--agree-tos', '-m', email, '--redirect', '-d', panel_domain)
    # A distinct Wings name needs its own hostname match. Without this, Nginx
    # commonly routes the challenge to an unrelated default site and returns 404.
    if wing_domain != panel_domain and wing_domain in missing:
        enable_acme_webroot_site(web, wing_domain)
        run('certbot', 'certonly', '--webroot', '-w', '/var/www/pterodactyl/public', '--non-interactive', '--agree-tos', '-m', email, '-d', wing_domain)