#!/usr/bin/env python3
"""IndoGeek's interactive Pterodactyl Panel + Wings installer (Debian/Ubuntu)."""
from __future__ import annotations

import getpass, json, os, platform, re, secrets, shutil, subprocess, sys, textwrap
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PANEL = Path('/var/www/pterodactyl')
ENV = PANEL / '.env'
WINGS_CONFIG = Path('/etc/pterodactyl/config.yml')

ART = r'''
  ___           _       ____           _    
 |_ _|_ __   __| | ___ / ___| ___  ___| | __
  | || '_ \ / _` |/ _ \ |  _ / _ \/ _ \ |/ /
  | || | | | (_| | (_) | |_| |  __/  __/   < 
 |___|_| |_|\__,_|\___/ \____|\___|\___|_|\_\
       Pterodactyl Installation
'''

def say(message: str, kind='INFO') -> None:
    print(f'[{kind}] {message}')

def ask(label: str, default: str | None = None, secret=False, required=True) -> str:
    suffix = f' [{default}]' if default else ''
    while True:
        value = (getpass.getpass if secret else input)(f'{label}{suffix}: ')
        value = value or (default or '')
        if value or not required:
            return value
        say('This value is required.', 'ERROR')

def confirm(question: str, default=False) -> bool:
    hint = 'Y/n' if default else 'y/N'
    return input(f'{question} [{hint}]: ').strip().lower() in ({'y', 'yes', ''} if default else {'y', 'yes'})

def run(*command: str, check=True, cwd: Path | None = None, env=None) -> subprocess.CompletedProcess:
    printable = ' '.join(command)
    say(f'$ {printable}', 'RUN')
    return subprocess.run(command, check=check, cwd=cwd, env=env, text=True)

def capture(*command: str) -> str:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()

def root_and_platform() -> None:
    if os.geteuid() != 0:
        sys.exit('Run this installer as root: sudo python3 install.py')
    if not Path('/etc/debian_version').exists():
        sys.exit('This initial release supports Debian and Ubuntu only. No changes were made.')

def installed(binary: str) -> bool:
    return shutil.which(binary) is not None

def apt(*packages: str) -> None:
    run('apt-get', 'update')
    run('apt-get', 'install', '-y', *packages)

def firewall(wings_port: str, sftp_port: str) -> None:
    if not confirm('Configure UFW firewall (SSH, HTTP, HTTPS, Wings and Wings SFTP)?'):
        say('Firewall configuration skipped. Open TCP 80, 443, %s, %s and your game allocation ports yourself.' % (wings_port, sftp_port), 'WARN')
        return
    if not installed('ufw'):
        apt('ufw')
    ssh_port = ask('Existing SSH port to keep open', '22')
    for port in (ssh_port, '80', '443', wings_port, sftp_port):
        run('ufw', 'allow', f'{port}/tcp')
    run('ufw', 'allow', 'in', 'on', 'pterodactyl0', 'comment', 'Pterodactyl Docker bridge', check=False)
    run('ufw', '--force', 'enable')
    say('UFW configured. Game-server allocation ports are workload-specific and are not opened automatically.', 'WARN')

def selected_webserver() -> str:
    nginx, apache = installed('nginx'), installed('apache2')
    if nginx and apache:
        sys.exit('Both Nginx and Apache are installed. Stop/remove one or configure the panel manually; refusing to guess.')
    if nginx: return 'nginx'
    if apache: return 'apache'
    while True:
        chosen = ask('Web server to install (nginx/apache)', 'nginx').lower()
        if chosen in {'nginx', 'apache'}:
            apt(chosen if chosen == 'nginx' else 'apache2')
            return chosen
        say('Choose nginx or apache.', 'ERROR')

def install_panel_dependencies(webserver: str) -> None:
    packages = ['curl','tar','unzip','git','ca-certificates','gnupg','redis-server','mariadb-server',
                'php8.3','php8.3-cli','php8.3-common','php8.3-gd','php8.3-mysql','php8.3-mbstring',
                'php8.3-bcmath','php8.3-xml','php8.3-curl','php8.3-zip']
    packages.append('php8.3-fpm')
    apt(*packages)
    if not installed('composer'):
        run('sh', '-c', 'curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer')
    run('systemctl', 'enable', '--now', 'mariadb', 'redis-server', 'php8.3-fpm')

def create_database(name: str, user: str, password: str) -> None:
    # Credentials travel through stdin/arguments only to the local MariaDB root socket; quote safely in SQL.
    def q(s): return "'" + s.replace('\\', '\\\\').replace("'", "''") + "'"
    sql = f'CREATE DATABASE IF NOT EXISTS `{name.replace("`", "``")}`; CREATE USER IF NOT EXISTS {q(user)}@\'127.0.0.1\' IDENTIFIED BY {q(password)}; GRANT ALL PRIVILEGES ON `{name.replace("`", "``")}`.* TO {q(user)}@\'127.0.0.1\'; FLUSH PRIVILEGES;'
    subprocess.run(['mariadb', '-e', sql], check=True)

def write_env(values: dict[str, str]) -> None:
    raw = (PANEL / '.env.example').read_text()
    for key, value in values.items():
        raw = re.sub(rf'^{re.escape(key)}=.*$', f'{key}={value}', raw, flags=re.M)
    ENV.write_text(raw)
    os.chmod(ENV, 0o640)

def panel_setup(domain: str, db: dict[str,str], admin: dict[str,str], mail: dict[str,str]) -> None:
    if PANEL.exists() and any(PANEL.iterdir()):
        sys.exit(f'{PANEL} is not empty. Refusing to overwrite an existing panel.')
    PANEL.mkdir(parents=True, exist_ok=True)
    run('curl', '-fL', '-o', 'panel.tar.gz', 'https://github.com/pterodactyl/panel/releases/latest/download/panel.tar.gz', cwd=PANEL)
    run('tar', '-xzf', 'panel.tar.gz', cwd=PANEL); (PANEL / 'panel.tar.gz').unlink()
    write_env({'APP_ENV':'production', 'APP_DEBUG':'false', 'APP_URL':f'https://{domain}',
               'DB_HOST':'127.0.0.1', 'DB_PORT':'3306', 'DB_DATABASE':db['name'], 'DB_USERNAME':db['user'],
               'DB_PASSWORD':db['password'], 'CACHE_DRIVER':'redis', 'SESSION_DRIVER':'redis', 'QUEUE_CONNECTION':'redis',
               'MAIL_MAILER':mail['driver'], 'MAIL_HOST':mail['host'], 'MAIL_PORT':mail['port'],
               'MAIL_USERNAME':mail['username'], 'MAIL_PASSWORD':mail['password'],
               'MAIL_ENCRYPTION':mail['encryption'], 'MAIL_FROM_ADDRESS':mail['from_address'], 'MAIL_FROM_NAME':mail['from_name']})
    env = os.environ | {'COMPOSER_ALLOW_SUPERUSER':'1'}
    run('composer', 'install', '--no-dev', '--optimize-autoloader', cwd=PANEL, env=env)
    run('php', 'artisan', 'key:generate', '--force', cwd=PANEL)
    run('php', 'artisan', 'migrate', '--seed', '--force', cwd=PANEL)
    # The command's non-interactive flags avoid recording the password in shell history.
    run('php', 'artisan', 'p:user:make', '--email', admin['email'], '--username', admin['username'], '--name-first', admin['first'], '--name-last', admin['last'], '--password', admin['password'], '--admin', '1', cwd=PANEL)
    run('chown', '-R', 'www-data:www-data', str(PANEL))
    run('chmod', '-R', '755', str(PANEL / 'storage'), str(PANEL / 'bootstrap/cache'))
    Path('/etc/cron.d/pterodactyl').write_text('* * * * * www-data php /var/www/pterodactyl/artisan schedule:run >> /dev/null 2>&1\n')
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
    run('systemctl', 'daemon-reload'); run('systemctl', 'enable', '--now', 'pteroq')

def webserver_config(web: str, domain: str) -> None:
    if web == 'nginx':
        Path('/etc/nginx/sites-available/pterodactyl.conf').write_text(textwrap.dedent(f'''\
            server {{
              listen 80; server_name {domain}; root /var/www/pterodactyl/public; index index.php;
              client_max_body_size 100m;
              location / {{ try_files $uri $uri/ /index.php?$query_string; }}
              location ~ \\.php$ {{ include snippets/fastcgi-php.conf; fastcgi_pass unix:/run/php/php8.3-fpm.sock; fastcgi_param PHP_VALUE "upload_max_filesize=100M \\n+              post_max_size=100M"; }}
              location ~ /\\.ht {{ deny all; }}
            }}
        '''))
        run('ln', '-sfn', '/etc/nginx/sites-available/pterodactyl.conf', '/etc/nginx/sites-enabled/pterodactyl.conf')
        run('nginx', '-t'); run('systemctl', 'reload', 'nginx')
    else:
        Path('/etc/apache2/sites-available/pterodactyl.conf').write_text(textwrap.dedent(f'''\
            <VirtualHost *:80>
              ServerName {domain}
              DocumentRoot /var/www/pterodactyl/public
              <Directory /var/www/pterodactyl/public>AllowOverride all Require all granted</Directory>
            </VirtualHost>
        '''))
        run('a2enmod', 'rewrite'); run('a2ensite', 'pterodactyl.conf'); run('systemctl', 'reload', 'apache2')

def ssl(web: str, panel_domain: str, wing_domain: str, email: str) -> None:
    domains = list(dict.fromkeys([panel_domain, wing_domain]))
    missing = [d for d in domains if not Path(f'/etc/letsencrypt/live/{d}/fullchain.pem').exists()]
    if not missing:
        say('Existing Let\'s Encrypt certificate(s) found.')
        return
    if not confirm('Obtain missing Let\'s Encrypt certificates now? DNS must already point here.'):
        say('SSL skipped; panel APP_URL remains HTTPS and will not work until certificates/configuration are completed.', 'WARN'); return
    apt('certbot', 'python3-certbot-nginx' if web == 'nginx' else 'python3-certbot-apache')
    if panel_domain in missing:
        run('certbot', '--nginx' if web == 'nginx' else '--apache', '--non-interactive', '--agree-tos', '-m', email, '--redirect', '-d', panel_domain)
    # A distinct Wings name has no virtual host. The existing Panel host serves the
    # ACME webroot challenge without changing its server_name configuration.
    if wing_domain != panel_domain and wing_domain in missing:
        run('certbot', 'certonly', '--webroot', '-w', '/var/www/pterodactyl/public', '--non-interactive', '--agree-tos', '-m', email, '-d', wing_domain)

def docker_and_wings() -> None:
    if not installed('docker'):
        if confirm('Install Docker CE using Docker\'s official convenience script?'):
            run('sh', '-c', 'curl -fsSL https://get.docker.com | sh')
        else: sys.exit('Wings requires Docker; stopping before Wings setup.')
    run('systemctl', 'enable', '--now', 'docker')
    version = tuple(map(int, re.findall(r'\d+', platform.release())[:2]))
    if version < (6, 1) and confirm('Enable Docker swap accounting (requires reboot after installation)?'):
        grub = Path('/etc/default/grub')
        if grub.exists():
            text = grub.read_text()
            if 'swapaccount=1' not in text:
                text = re.sub(r'^(GRUB_CMDLINE_LINUX(?:_DEFAULT)?="[^\n]*)"', r'\1 swapaccount=1"', text, flags=re.M)
                grub.write_text(text); run('update-grub')
            say('swapaccount=1 set. Reboot later to activate it.', 'WARN')
    Path('/etc/pterodactyl').mkdir(exist_ok=True)
    arch = 'amd64' if platform.machine() in {'x86_64','amd64'} else 'arm64'
    run('curl', '-fL', '-o', '/usr/local/bin/wings', f'https://github.com/pterodactyl/wings/releases/latest/download/wings_linux_{arch}')
    run('chmod', '755', '/usr/local/bin/wings')
    Path('/etc/systemd/system/wings.service').write_text(textwrap.dedent('''\
        [Unit]
        Description=Pterodactyl Wings Daemon
        After=docker.service
        Requires=docker.service
        PartOf=docker.service
        [Service]
        User=root
        WorkingDirectory=/etc/pterodactyl
        LimitNOFILE=4096
        PIDFile=/var/run/wings/daemon.pid
        ExecStart=/usr/local/bin/wings
        Restart=on-failure
        StartLimitInterval=180
        StartLimitBurst=30
        RestartSec=5s
        [Install]
        WantedBy=multi-user.target
    '''))

def api(base: str, key: str, method: str, endpoint: str, payload=None):
    req = Request(base.rstrip('/') + '/api/application' + endpoint, method=method,
                  headers={'Authorization':f'Bearer {key}', 'Accept':'Application/vnd.pterodactyl.v1+json', 'Content-Type':'application/json'},
                  data=json.dumps(payload).encode() if payload else None)
    try:
        with urlopen(req) as response: return json.load(response)
    except HTTPError as exc:
        sys.exit(f'Panel API request failed ({exc.code}): {exc.read().decode()[:600]}')

def yaml_dump(obj, indent=0):
    # Panel returns a JSON-compatible Wings config; this small emitter covers its scalar/list/map structure.
    pad = ' ' * indent
    if isinstance(obj, dict):
        lines=[]
        for k,v in obj.items():
            if isinstance(v, (dict,list)): lines += [f'{pad}{k}:', yaml_dump(v, indent+2)]
            else: lines.append(f'{pad}{k}: {yaml_scalar(v)}')
        return '\n'.join(lines)
    if isinstance(obj, list):
        return '\n'.join(f'{pad}- {yaml_scalar(v)}' if not isinstance(v,(dict,list)) else f'{pad}-\n{yaml_dump(v,indent+2)}' for v in obj)
    return pad + yaml_scalar(obj)
def yaml_scalar(v):
    if v is None: return 'null'
    if v is True: return 'true'
    if v is False: return 'false'
    if isinstance(v, (int,float)): return str(v)
    return json.dumps(str(v))

def provision_node(panel_domain: str, wing_domain: str, admin_email: str, port: str, sftp: str) -> None:
    say('A Panel *Application API key* is required to create nodes. Login credentials cannot create nodes via the supported API.', 'NOTE')
    say('After logging into the panel: Administration > Application API > Create New, grant READ/WRITE and paste its key.', 'NOTE')
    key = ask('Application API key', secret=True)
    location_name = ask('Node location short name', 'local')
    location_desc = ask('Node location description', location_name)
    loc = api(f'https://{panel_domain}', key, 'POST', '/locations', {'short':location_name, 'long':location_desc})
    loc_id = loc['attributes']['id']
    node_name=ask('Node name', 'node-1'); memory=int(ask('Node memory limit in MiB', '4096')); disk=int(ask('Node disk limit in MiB', '20480'))
    public_ip=ask('Public allocation IP', capture('hostname','-I').split()[0])
    scheme='https' if Path(f'/etc/letsencrypt/live/{wing_domain}/fullchain.pem').exists() else 'http'
    payload={'name':node_name,'location_id':loc_id,'fqdn':wing_domain,'scheme':scheme,'behind_proxy':False,
             'maintenance_mode':False,'memory':memory,'memory_overallocate':0,'disk':disk,'disk_overallocate':0,
             'upload_size':100,'daemon_sftp':int(sftp),'daemon_listen':int(port),'description':'Provisioned by IndoGeek installer'}
    node=api(f'https://{panel_domain}',key,'POST','/nodes',payload); node_id=node['attributes']['id']
    api(f'https://{panel_domain}',key,'POST',f'/nodes/{node_id}/allocations',{'ip':public_ip,'ports':['25565-25565']})
    cfg=api(f'https://{panel_domain}',key,'GET',f'/nodes/{node_id}/configuration')
    attrs=cfg['attributes']; config=attrs.get('config', attrs)
    WINGS_CONFIG.write_text(config if isinstance(config,str) else yaml_dump(config)+'\n')
    run('systemctl','daemon-reload'); run('systemctl','enable','--now','wings')
    say(f'Node {node_name} provisioned. A default allocation {public_ip}:25565 was added; add your required ranges in the panel.', 'OK')

def main():
    print(ART); root_and_platform()
    say('This installer downloads official releases and changes system services, web-server config, MariaDB, Docker, and optionally UFW.', 'WARN')
    if not confirm('Continue?'): return
    panel_domain=ask('Panel FQDN (e.g. panel.example.com)')
    wing_domain=ask('Wings FQDN (leave blank to reuse Panel FQDN)', required=False) or panel_domain
    if wing_domain == panel_domain: say('Wings shares the panel FQDN. Disable Cloudflare proxying (orange cloud) for Wings traffic.', 'WARN')
    wings_port=ask('Wings API port', '8080'); wings_sftp=ask('Wings SFTP port', '2022')
    web=selected_webserver(); install_panel_dependencies(web)
    db={'name':ask('Database name','panel'),'user':ask('Database user','pterodactyl'),'password':ask('Database password', secrets.token_urlsafe(24), secret=True)}
    admin={'email':ask('Administrator email'),'username':ask('Administrator username','admin'),'first':ask('Administrator first name','Admin'),'last':ask('Administrator last name','User'),'password':ask('Administrator password',secret=True)}
    say('Mail is configured directly in .env. Use SMTP in production; `log` writes mail to Laravel logs.', 'NOTE')
    driver=ask('Mail driver (smtp/log)', 'smtp').lower()
    mail={'driver':driver, 'host':ask('SMTP host', required=driver == 'smtp'), 'port':ask('SMTP port', '587' if driver == 'smtp' else '2525'),
          'username':ask('SMTP username', required=False), 'password':ask('SMTP password', secret=True, required=False),
          'encryption':ask('SMTP encryption (tls/ssl/blank)', 'tls' if driver == 'smtp' else '', required=False),
          'from_address':ask('Mail from address', admin['email']), 'from_name':ask('Mail from name', 'Pterodactyl')}
    create_database(**db); panel_setup(panel_domain,db,admin,mail); webserver_config(web,panel_domain); ssl(web, panel_domain, wing_domain, admin['email'])
    docker_and_wings(); firewall(wings_port,wings_sftp)
    if confirm('Create the Panel node through the supported Application API and start Wings now?'):
        provision_node(panel_domain,wing_domain,admin['email'],wings_port,wings_sftp)
    else: say('Wings binary and service are installed but not started. Add a node in the panel, save its config to /etc/pterodactyl/config.yml, then run: systemctl enable --now wings', 'WARN')
    say('Installation completed. Save the APP_KEY securely: grep APP_KEY /var/www/pterodactyl/.env', 'OK')

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('\nCancelled. Completed changes were not rolled back.'); sys.exit(130)
