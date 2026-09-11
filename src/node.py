"""Wings node provisioning through the Pterodactyl Application API."""
from __future__ import annotations

from pathlib import Path

from . import config
from .apiclient import api, find_by_attribute, yaml_dump
from .ui import ask, say
from .utils import capture, run


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
        loc = api(base, key, 'POST', '/locations', {'short': location_name, 'long': location_desc})
        loc_id = loc['attributes']['id']
    node_name = ask('Node name', 'node-1')
    memory = int(ask('Node memory limit in MiB', '4096'))
    disk = int(ask('Node disk limit in MiB', '20480'))
    public_ip = ask('Public allocation IP', capture('hostname', '-I').split()[0])
    scheme = 'https' if Path(f'/etc/letsencrypt/live/{wing_domain}/fullchain.pem').exists() else 'http'
    payload = {'name': node_name, 'location_id': loc_id, 'fqdn': wing_domain, 'scheme': scheme, 'behind_proxy': False,
               'maintenance_mode': False, 'memory': memory, 'memory_overallocate': 0, 'disk': disk, 'disk_overallocate': 0,
               'upload_size': 100, 'daemon_sftp': int(sftp), 'daemon_listen': int(port), 'description': 'Provisioned by IndoGeek installer'}
    existing_node = find_by_attribute(api(base, key, 'GET', '/nodes'), 'name', node_name)
    if existing_node:
        node_id = existing_node['id']
        say(f'Reusing existing node {node_name} (ID {node_id}).', 'NOTE')
    else:
        node = api(base, key, 'POST', '/nodes', payload)
        node_id = node['attributes']['id']
    allocations = api(base, key, 'GET', f'/nodes/{node_id}/allocations')
    allocation_exists = any(a.get('attributes', {}).get('ip') == public_ip and
                            a.get('attributes', {}).get('port') == 25565
                            for a in allocations.get('data', []))
    if allocation_exists:
        say(f'Reusing existing allocation {public_ip}:25565.', 'NOTE')
    else:
        api(base, key, 'POST', f'/nodes/{node_id}/allocations', {'ip': public_ip, 'ports': ['25565-25565']})
    cfg = api(base, key, 'GET', f'/nodes/{node_id}/configuration')
    # Panel versions return this endpoint either as a normal API resource
    # (``attributes``) or as the raw Wings configuration object.
    attrs = cfg.get('attributes', cfg)
    wings_config = attrs.get('config', attrs)
    config.WINGS_CONFIG.write_text(wings_config if isinstance(wings_config, str) else yaml_dump(wings_config) + '\n')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'wings')
    say(f'Node {node_name} provisioned. A default allocation {public_ip}:25565 was added; add your required ranges in the panel.', 'OK')