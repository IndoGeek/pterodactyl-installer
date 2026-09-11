"""Optional UFW configuration."""
from __future__ import annotations

from .packages import apt
from .ui import ask, confirm, say
from .utils import installed, run


def firewall(wings_port: str, sftp_port: str) -> list:
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