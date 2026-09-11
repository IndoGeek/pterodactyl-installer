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
# The state contains database and administrator credentials, so it must never be
# world-readable.  It is removed after a successful install.
STATE_FILE = Path('/var/lib/pterodactyl-installer/state.json')
MANIFEST_FILE = Path('/var/lib/pterodactyl-installer/manifest.json')
SUPPORTED_PHP_VERSIONS = ('8.3', '8.2')
INSTALLED_BY_INSTALLER: list[str] = []

ART = r'''
  ___           _       ____           _    
 |_ _|_ __   __| | ___ / ___| ___  ___| | __
  | || '_ \ / _` |/ _ \ |  _ / _ \/ _ \ |/ /
  | || | | | (_| | (_) | |_| |  __/  __/   < 
 |___|_| |_|\__,_|\___/ \____|\___|\___|_|\_\
       Pterodactyl Installation
'''

COMPLETE_ART = r'''
   ___           _       ____           _      _
  |_ _|_ __   __| | ___ / ___| ___  ___| | __ | |
   | || '_ \ / _` |/ _ \ |  _ / _ \/ _ \ |/ / | |
   | || | | | (_| | (_) | |_| |  __/  __/   <  |_|
  |___|_| |_|\__,_|\___/ \____|\___|\___|_|\_\ (_)
                 Installation Complete
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

def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(STATE_FILE)
    os.chmod(STATE_FILE, 0o600)

def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f'Cannot read installer resume state {STATE_FILE}: {exc}')
    if not isinstance(state, dict) or 'config' not in state or 'completed' not in state:
        sys.exit(f'Installer resume state {STATE_FILE} is invalid. Move it aside only if you intend to start over.')
    return state

def complete_phase(state: dict, phase: str) -> None:
    if phase not in state['completed']:
        state['completed'].append(phase)
    save_state(state)
    say(f'Checkpoint saved: {phase}', 'OK')

def root_and_platform() -> None:
    if os.geteuid() != 0:
        sys.exit('Run this installer as root: sudo python3 install.py')
    if not Path('/etc/debian_version').exists():
        sys.exit('This initial release supports Debian and Ubuntu only. No changes were made.')

def installed(binary: str) -> bool:
    return shutil.which(binary) is not None

def select_php_version() -> str:
    """Prefer an installed PHP version supported by the current Panel series."""
    for version in SUPPORTED_PHP_VERSIONS:
        if installed(f'php{version}'):
            say(f'Using installed, Pterodactyl-supported PHP {version}.')
            return version
    # Pterodactyl's official 1.12 requirements recommend 8.3.
    say('No supported PHP version found; PHP 8.3 will be installed.', 'NOTE')
    return '8.3'

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

def firewall(wings_port: str, sftp_port: str) -> list[str]:
    ssh_port = ask('Existing SSH port to keep open', '22')
    ports = [(ssh_port, 'SSH'), ('80', 'HTTP'), ('443', 'HTTPS'),
             (wings_port, 'Wings API'), (sftp_port, 'Wings SFTP')]
    selected = []
    skipped = []
    for port, purpose in ports:
        (selected if confirm(f'Open TCP {port} for {purpose} in UFW?', default=True) else skipped).append(port)
    if not selected:
        say('No UFW rules were requested.', 'WARN')
        return skipped
    if not installed('ufw'):
        apt('ufw')
    for port in selected:
        run('ufw', 'allow', f'{port}/tcp')
    run('ufw', 'allow', 'in', 'on', 'pterodactyl0', 'comment', 'Pterodactyl Docker bridge', check=False)
    run('ufw', '--force', 'enable')
    say('UFW configured. Game-server allocation ports are workload-specific and are not opened automatically.', 'WARN')
    return skipped

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

def install_panel_dependencies(webserver: str, php_version: str) -> None:
    packages = ['curl','tar','unzip','git','ca-certificates','gnupg','redis-server','mariadb-server',
                ]
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

def php_fpm_socket(version: str) -> str:
    socket = f'/run/php/php{version}-fpm.sock'
    if not Path(socket).exists():
        sys.exit(f'PHP-FPM socket {socket} was not found. Check the php{version}-fpm service.')
    return socket

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

def write_scheduler(php_version: str) -> None:
    # /etc/cron.d requires a user field; this is the system-cron equivalent of
    # Pterodactyl's official every-minute schedule:run entry.
    Path('/etc/cron.d/pterodactyl').write_text(
        f'* * * * * www-data /usr/bin/php{php_version} /var/www/pterodactyl/artisan schedule:run >> /dev/null 2>&1\n')

def panel_setup(domain: str, db: dict[str,str], admin: dict[str,str], mail: dict[str,str], php_version: str) -> None:
    # A prior interrupted installer run may already have extracted the release.
    # Only reject an unrelated directory; continue safely from an extracted panel.
    if PANEL.exists() and any(PANEL.iterdir()) and not (PANEL / '.env.example').exists():
        sys.exit(f'{PANEL} is not a recognizable panel installation. Refusing to overwrite it.')
    # This also handles installations interrupted after pteroq was enabled, as
    # happened after the old Nginx configuration was written.
    prepared_panel = ENV.exists() and (PANEL / 'vendor/autoload.php').exists() and Path('/etc/systemd/system/pteroq.service').exists()
    if prepared_panel:
        say('Existing prepared Panel detected; preserving its .env and administrator account.')
        write_scheduler(php_version)
        return
    PANEL.mkdir(parents=True, exist_ok=True)
    if not (PANEL / '.env.example').exists():
        run('curl', '-fL', '-o', 'panel.tar.gz', 'https://github.com/pterodactyl/panel/releases/latest/download/panel.tar.gz', cwd=PANEL)
        run('tar', '-xzf', 'panel.tar.gz', cwd=PANEL)
        (PANEL / 'panel.tar.gz').unlink(missing_ok=True)
    write_env({'APP_ENV':'production', 'APP_DEBUG':'false', 'APP_URL':f'https://{domain}',
               'DB_HOST':'127.0.0.1', 'DB_PORT':'3306', 'DB_DATABASE':db['name'], 'DB_USERNAME':db['user'],
               'DB_PASSWORD':db['password'], 'CACHE_DRIVER':'redis', 'SESSION_DRIVER':'redis', 'QUEUE_CONNECTION':'redis',
               'MAIL_MAILER':mail['driver'], 'MAIL_HOST':mail['host'], 'MAIL_PORT':mail['port'],
               'MAIL_USERNAME':mail['username'], 'MAIL_PASSWORD':mail['password'],
               'MAIL_ENCRYPTION':mail['encryption'], 'MAIL_FROM_ADDRESS':mail['from_address'], 'MAIL_FROM_NAME':mail['from_name']})
    env = os.environ | {'COMPOSER_ALLOW_SUPERUSER':'1'}
    php_bin = f'php{php_version}'
    run(php_bin, '/usr/local/bin/composer', 'install', '--no-dev', '--optimize-autoloader', cwd=PANEL, env=env)
    run(php_bin, 'artisan', 'key:generate', '--force', cwd=PANEL)
    run(php_bin, 'artisan', 'migrate', '--seed', '--force', cwd=PANEL)
    # The command's non-interactive flags avoid recording the password in shell history.
    run(php_bin, 'artisan', 'p:user:make', '--email', admin['email'], '--username', admin['username'], '--name-first', admin['first'], '--name-last', admin['last'], '--password', admin['password'], '--admin', '1', cwd=PANEL)
    run('chown', '-R', 'www-data:www-data', str(PANEL))
    run('chmod', '-R', '755', str(PANEL / 'storage'), str(PANEL / 'bootstrap/cache'))
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
    run('systemctl', 'daemon-reload'); run('systemctl', 'enable', '--now', 'pteroq')

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
        run('nginx', '-t'); run('systemctl', 'reload', 'nginx')
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
        run('a2ensite', 'pterodactyl-wings-acme.conf'); run('systemctl', 'reload', 'apache2')

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
    # A distinct Wings name needs its own hostname match. Without this, Nginx
    # commonly routes the challenge to an unrelated default site and returns 404.
    if wing_domain != panel_domain and wing_domain in missing:
        enable_acme_webroot_site(web, wing_domain)
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
    wings_binary = Path('/usr/local/bin/wings')
    if wings_binary.exists():
        say('Wings binary already exists; leaving it unchanged.')
    else:
        run('curl', '-fL', '-o', str(wings_binary), f'https://github.com/pterodactyl/wings/releases/latest/download/wings_linux_{arch}')
        run('chmod', '755', str(wings_binary))
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
                  # Cloudflare often blocks Python's default ``Python-urllib``
                  # signature before the request can reach the Panel API.
                  headers={'Authorization':f'Bearer {key}', 'Accept':'Application/vnd.pterodactyl.v1+json', 'Content-Type':'application/json',
                           'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'},
                  data=json.dumps(payload).encode() if payload else None)
    try:
        with urlopen(req) as response:
            # Several successful Panel API endpoints (including allocation
            # creation) reply with HTTP 204 and no JSON response body.
            body = response.read()
            return json.loads(body) if body.strip() else {}
    except HTTPError as exc:
        detail = exc.read().decode()[:600]
        if exc.code == 403 and ('cloudflare' in detail.lower() or 'error 1010' in detail.lower()):
            sys.exit('Cloudflare blocked the request before it reached the Panel API. The installer now uses a browser-compatible user-agent; rerun it. If this persists, temporarily set the Panel DNS record to DNS-only or add a Cloudflare WAF allow/skip rule for this server\'s public IP on /api/application/*.')
        sys.exit(f'Panel API request failed ({exc.code}): {detail}')

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

def find_by_attribute(response: dict, attribute: str, value):
    """Return the first matching item from a standard Pterodactyl API list."""
    for item in response.get('data', []):
        attributes = item.get('attributes', {})
        if attributes.get(attribute) == value:
            return attributes
    return None

def provision_node(panel_domain: str, wing_domain: str, admin_email: str, port: str, sftp: str) -> None:
    say('Wings is installed and waiting for Panel provisioning.', 'NOTE')
    say('1. Open https://%s and log in as the administrator.' % panel_domain, 'NOTE')
    say('2. Go to Administration > Application API > Create New.', 'NOTE')
    say('3. Give the key read/write access to Locations and Nodes (and Allocations), then copy it now.', 'NOTE')
    say('Only an Application API key works here; a Client API key or login password will be rejected.', 'NOTE')
    key = ask('Application API key', secret=True)
    location_name = ask('Node location short name', 'local')
    location_desc = ask('Node location description', location_name)
    base = f'https://{panel_domain}'
    existing_location = find_by_attribute(api(base, key, 'GET', '/locations'), 'short', location_name)
    if existing_location:
        loc_id = existing_location['id']
        say(f'Reusing existing location {location_name} (ID {loc_id}).', 'NOTE')
    else:
        loc = api(base, key, 'POST', '/locations', {'short':location_name, 'long':location_desc})
        loc_id = loc['attributes']['id']
    node_name=ask('Node name', 'node-1'); memory=int(ask('Node memory limit in MiB', '4096')); disk=int(ask('Node disk limit in MiB', '20480'))
    public_ip=ask('Public allocation IP', capture('hostname','-I').split()[0])
    scheme='https' if Path(f'/etc/letsencrypt/live/{wing_domain}/fullchain.pem').exists() else 'http'
    payload={'name':node_name,'location_id':loc_id,'fqdn':wing_domain,'scheme':scheme,'behind_proxy':False,
             'maintenance_mode':False,'memory':memory,'memory_overallocate':0,'disk':disk,'disk_overallocate':0,
             'upload_size':100,'daemon_sftp':int(sftp),'daemon_listen':int(port),'description':'Provisioned by IndoGeek installer'}
    existing_node = find_by_attribute(api(base, key, 'GET', '/nodes'), 'name', node_name)
    if existing_node:
        node_id = existing_node['id']
        say(f'Reusing existing node {node_name} (ID {node_id}).', 'NOTE')
    else:
        node=api(base,key,'POST','/nodes',payload); node_id=node['attributes']['id']
    allocations = api(base, key, 'GET', f'/nodes/{node_id}/allocations')
    allocation_exists = any(a.get('attributes', {}).get('ip') == public_ip and
                            a.get('attributes', {}).get('port') == 25565
                            for a in allocations.get('data', []))
    if allocation_exists:
        say(f'Reusing existing allocation {public_ip}:25565.', 'NOTE')
    else:
        api(base,key,'POST',f'/nodes/{node_id}/allocations',{'ip':public_ip,'ports':['25565-25565']})
    cfg=api(base,key,'GET',f'/nodes/{node_id}/configuration')
    # Panel versions return this endpoint either as a normal API resource
    # (``attributes``) or as the raw Wings configuration object.
    attrs = cfg.get('attributes', cfg)
    config = attrs.get('config', attrs)
    WINGS_CONFIG.write_text(config if isinstance(config,str) else yaml_dump(config)+'\n')
    run('systemctl','daemon-reload'); run('systemctl','enable','--now','wings')
    say(f'Node {node_name} provisioned. A default allocation {public_ip}:25565 was added; add your required ranges in the panel.', 'OK')

def completion_summary(config: dict) -> None:
    print(COMPLETE_ART)
    say(f"Panel: https://{config['panel_domain']}", 'OK')
    say(f"Administrator: {config['admin']['username']} ({config['admin']['email']})", 'OK')
    say(f"Wings: {config['wing_domain']} — API port {config['wings_port']}, SFTP port {config['wings_sftp']}", 'OK')
    say(f"PHP runtime: {config['php_version']} | Scheduler: /etc/cron.d/pterodactyl (runs every minute)", 'OK')
    say('Services to check: systemctl status pteroq wings docker nginx', 'NOTE')
    say('Delete the Application API key you created: Panel → Administration → Application API → delete/revoke that key.', 'WARN')
    say('Keep the Wings DNS record DNS-only (not proxied by Cloudflare), and open game allocation ports separately.', 'WARN')

def write_manifest(config: dict) -> None:
    """Persist only uninstall metadata; credentials are deliberately excluded."""
    manifest = {
        'panel_domain': config['panel_domain'], 'wing_domain': config['wing_domain'],
        'web': config['web'], 'php_version': config['php_version'],
        'packages': sorted(set(INSTALLED_BY_INSTALLER)),
        'database_name': config['db']['name'], 'database_user': config['db']['user'],
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
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(MANIFEST_FILE, 0o600)

def install_uninstaller() -> None:
    source = Path(__file__).with_name('uninstall.py')
    target = Path('/usr/local/sbin/pterodactyl-uninstall.py')
    if source.exists():
        shutil.copyfile(source, target)
        os.chmod(target, 0o700)
        say(f'Selective uninstaller installed at {target}.', 'OK')

def clear_resume_state() -> None:
    STATE_FILE.unlink(missing_ok=True)
    STATE_FILE.with_suffix('.tmp').unlink(missing_ok=True)

def main():
    print(ART); root_and_platform()
    say('This installer downloads official releases and changes system services, web-server config, MariaDB, Docker, and optionally UFW.', 'WARN')
    state = load_state()
    if state:
        say('Resuming the interrupted installation. Completed phases: ' +
            (', '.join(state['completed']) or 'none'), 'NOTE')
    else:
        if not confirm('Continue?'): return
        panel_domain=ask('Panel FQDN (e.g. panel.example.com)')
        wing_domain=ask('Wings FQDN (leave blank to reuse Panel FQDN)', required=False) or panel_domain
        wings_port=ask('Wings API port', '8080'); wings_sftp=ask('Wings SFTP port', '2022')
        web=selected_webserver()
        php_version=select_php_version()
        db={'name':ask('Database name','panel'),'user':ask('Database user','pterodactyl'),'password':ask('Database password', secrets.token_urlsafe(24), secret=True)}
        admin={'email':ask('Administrator email'),'username':ask('Administrator username','admin'),'first':ask('Administrator first name','Admin'),'last':ask('Administrator last name','User'),'password':ask('Administrator password',secret=True)}
        if confirm('Configure an SMTP mail server now?', default=False):
            say('Use SMTP credentials from your mail provider. They are stored in the Panel .env file.', 'NOTE')
            mail={'driver':'smtp', 'host':ask('SMTP host'), 'port':ask('SMTP port', '587'),
                  'username':ask('SMTP username', required=False), 'password':ask('SMTP password', secret=True, required=False),
                  'encryption':ask('SMTP encryption (tls/ssl/blank)', 'tls', required=False),
                  'from_address':ask('Mail from address', admin['email']), 'from_name':ask('Mail from name', 'Pterodactyl')}
        else:
            mail={'driver':'log', 'host':'', 'port':'', 'username':'', 'password':'', 'encryption':'',
                  'from_address':admin['email'], 'from_name':'Pterodactyl'}
        state = {'config': {'panel_domain': panel_domain, 'wing_domain': wing_domain,
                 'wings_port': wings_port, 'wings_sftp': wings_sftp, 'web': web, 'php_version': php_version,
                 'db': db, 'admin': admin, 'mail': mail}, 'completed': []}
        save_state(state)
        say(f'Resume state saved to {STATE_FILE} (root-only).', 'NOTE')

    config = state['config']; completed = state['completed']
    # Resume states written by older installer versions did not pin PHP.
    if 'php_version' not in config:
        config['php_version'] = select_php_version()
        save_state(state)
    panel_domain, wing_domain = config['panel_domain'], config['wing_domain']
    if wing_domain == panel_domain: say('Wings shares the panel FQDN. Disable Cloudflare proxying (orange cloud) for Wings traffic.', 'WARN')
    if 'dependencies' not in completed:
        install_panel_dependencies(config['web'], config['php_version']); complete_phase(state, 'dependencies')
    if 'database' not in completed:
        create_database(**config['db']); complete_phase(state, 'database')
    if 'panel' not in completed:
        panel_setup(panel_domain, config['db'], config['admin'], config['mail'], config['php_version']); complete_phase(state, 'panel')
    if 'webserver' not in completed:
        webserver_config(config['web'], panel_domain, config['php_version']); complete_phase(state, 'webserver')
    if 'ssl' not in completed:
        ssl(config['web'], panel_domain, wing_domain, config['admin']['email']); complete_phase(state, 'ssl')
    if 'wings' not in completed:
        docker_and_wings(); complete_phase(state, 'wings')
    if 'firewall' not in completed:
        config['unopened_ports'] = firewall(config['wings_port'], config['wings_sftp'])
        save_state(state); complete_phase(state, 'firewall')
    if 'node' not in completed:
        if confirm('Create the Panel node through the supported Application API and start Wings now?', default=True):
            provision_node(panel_domain, wing_domain, config['admin']['email'], config['wings_port'], config['wings_sftp'])
        else: say('Wings binary and service are installed but not started. Add a node in the panel, save its config to /etc/pterodactyl/config.yml, then run: systemctl enable --now wings', 'WARN')
        complete_phase(state, 'node')
    if config.get('unopened_ports'):
        say('You chose not to open these TCP ports in UFW: %s. Open any that this server needs before using the Panel/Wings.' % ', '.join(config['unopened_ports']), 'WARN')
    say('Also open every game-server allocation port you add in the Panel; those ports are intentionally not managed automatically.', 'WARN')
    completion_summary(config)
    say('Installation completed. Save the APP_KEY securely: grep APP_KEY /var/www/pterodactyl/.env', 'OK')
    write_manifest(config)
    install_uninstaller()
    clear_resume_state()

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('\nCancelled. Completed changes were not rolled back.'); sys.exit(130)
