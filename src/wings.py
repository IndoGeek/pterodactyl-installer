"""Docker installation and the Wings daemon service."""
from __future__ import annotations

import platform
import re
import sys
import textwrap
from pathlib import Path

from .ui import confirm, say
from .utils import installed, run


def docker_and_wings() -> None:
    if not installed('docker'):
        if confirm('Install Docker CE using Docker\'s official convenience script?'):
            run('sh', '-c', 'curl -fsSL https://get.docker.com | sh')
        else:
            sys.exit('Wings requires Docker; stopping before Wings setup.')
    run('systemctl', 'enable', '--now', 'docker')
    version = tuple(map(int, re.findall(r'\d+', platform.release())[:2]))
    if version < (6, 1) and confirm('Enable Docker swap accounting (requires reboot after installation)?'):
        grub = Path('/etc/default/grub')
        if grub.exists():
            text = grub.read_text()
            if 'swapaccount=1' not in text:
                text = re.sub(r'^(GRUB_CMDLINE_LINUX(?:_DEFAULT)?="[^\n]*)"', r'\1 swapaccount=1"', text, flags=re.M)
                grub.write_text(text)
                run('update-grub')
            say('swapaccount=1 set. Reboot later to activate it.', 'WARN')
    Path('/etc/pterodactyl').mkdir(exist_ok=True)
    arch = 'amd64' if platform.machine() in {'x86_64', 'amd64'} else 'arm64'
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