"""Nginx/Apache configuration for the Panel and the Wings ACME hostname."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from .packages import apt
from .php import php_fpm_socket
from .ui import ask, say
from .utils import installed, run


def selected_webserver() -> str:
    nginx, apache = installed('nginx'), installed('apache2')
    if nginx and apache:
        sys.exit('Both Nginx and Apache are installed. Stop/remove one or configure the panel manually; refusing to guess.')
    if nginx:
        return 'nginx'
    if apache:
        return 'apache'
    while True:
        chosen = ask('Web server to install (nginx/apache)', 'nginx').lower()
        if chosen in {'nginx', 'apache'}:
            apt(chosen if chosen == 'nginx' else 'apache2')
            return chosen
        say('Choose nginx or apache.', 'ERROR')


def webserver_config(web: str, domain: str, php_version: str) -> None:
    if web == 'nginx':
        Path('/etc/nginx/sites-available/pterodactyl.conf').write_text(textwrap.dedent(f'''\
            server {{
              listen 80; server_name {domain}; root /var/www/pterodactyl/public; index index.php;
              client_max_body_size 100m;
              location / {{ try_files $uri $uri/ /index.php?$query_string; }}
              location ~ \\.php$ {{
                try_files $uri =404;
                include fastcgi_params;
                fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
                fastcgi_param PHP_VALUE "upload_max_filesize=100M \\npost_max_size=100M";
                fastcgi_pass unix:{php_fpm_socket(php_version)};
              }}
              location ~ /\\.ht {{ deny all; }}
            }}
        '''))
        run('ln', '-sfn', '/etc/nginx/sites-available/pterodactyl.conf', '/etc/nginx/sites-enabled/pterodactyl.conf')
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
    else:
        Path('/etc/apache2/sites-available/pterodactyl.conf').write_text(textwrap.dedent(f'''\
            <VirtualHost *:80>
              ServerName {domain}
              DocumentRoot /var/www/pterodactyl/public
              <Directory /var/www/pterodactyl/public>AllowOverride all Require all granted</Directory>
            </VirtualHost>
        '''))
        run('a2enmod', 'rewrite')
        run('a2ensite', 'pterodactyl.conf')
        run('systemctl', 'reload', 'apache2')


def apply_ssl(web: str, domain: str, php_version: str) -> Path | None:
    """Point the panel site at the Let's Encrypt certificate with an HTTPS server block.

    Certbot's plugin-injected edits live inside the site file, so a later webserver
    rewrite drops them. Rewriting the site from our own template keeps SSL
    deterministic and idempotent. Returns the written config path, or None when no
    certificate exists for ``domain`` (callers should only call this once the
    certificate is known to exist)."""
    fullchain = Path('/etc/letsencrypt/live') / domain / 'fullchain.pem'
    privkey = Path('/etc/letsencrypt/live') / domain / 'privkey.pem'
    if not (fullchain.exists() and privkey.exists()):
        return None
    if web == 'nginx':
        Path('/etc/nginx/sites-available/pterodactyl.conf').write_text(textwrap.dedent(f'''\
            server {{
              listen 80;
              server_name {domain};
              return 301 https://$server_name$request_uri;
            }}

            server {{
              listen 443 ssl http2;
              server_name {domain};
              root /var/www/pterodactyl/public;
              index index.php;
              client_max_body_size 100m;
              ssl_certificate {fullchain};
              ssl_certificate_key {privkey};
              location / {{ try_files $uri $uri/ /index.php?$query_string; }}
              location ~ \\.php$ {{
                try_files $uri =404;
                include fastcgi_params;
                fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
                fastcgi_param PHP_VALUE "upload_max_filesize=100M \\npost_max_size=100M";
                fastcgi_pass unix:{php_fpm_socket(php_version)};
              }}
              location ~ /\\.ht {{ deny all; }}
            }}
        '''))
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        return Path('/etc/nginx/sites-available/pterodactyl.conf')
    Path('/etc/apache2/sites-available/pterodactyl.conf').write_text(textwrap.dedent(f'''\
        <VirtualHost *:80>
          ServerName {domain}
          Redirect permanent / https://{domain}/
        </VirtualHost>
        <VirtualHost *:443>
          ServerName {domain}
          DocumentRoot /var/www/pterodactyl/public
          SSLEngine on
          SSLCertificateFile {fullchain}
          SSLCertificateKeyFile {privkey}
          <Directory /var/www/pterodactyl/public>AllowOverride all Require all granted</Directory>
        </VirtualHost>
    '''))
    run('a2enmod', 'ssl')
    run('systemctl', 'reload', 'apache2')
    return Path('/etc/apache2/sites-available/pterodactyl.conf')


def enable_acme_webroot_site(web: str, domain: str) -> None:
    """Route a distinct Wings hostname to the Certbot webroot on port 80."""
    if web == 'nginx':
        Path('/etc/nginx/sites-available/pterodactyl-wings-acme.conf').write_text(textwrap.dedent(f'''\
            server {{
              listen 80;
              server_name {domain};
              root /var/www/pterodactyl/public;
              location ^~ /.well-known/acme-challenge/ {{ try_files $uri =404; }}
              location / {{ return 404; }}
            }}
        '''))
        run('ln', '-sfn', '/etc/nginx/sites-available/pterodactyl-wings-acme.conf', '/etc/nginx/sites-enabled/pterodactyl-wings-acme.conf')
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
    else:
        Path('/etc/apache2/sites-available/pterodactyl-wings-acme.conf').write_text(textwrap.dedent(f'''\
            <VirtualHost *:80>
              ServerName {domain}
              DocumentRoot /var/www/pterodactyl/public
              Alias /.well-known/acme-challenge/ /var/www/pterodactyl/public/.well-known/acme-challenge/
              <Directory /var/www/pterodactyl/public/.well-known/acme-challenge>
                Require all granted
              </Directory>
            </VirtualHost>
        '''))
        run('a2ensite', 'pterodactyl-wings-acme.conf')
        run('systemctl', 'reload', 'apache2')