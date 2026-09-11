"""Final installation summary."""
from __future__ import annotations

from .art import COMPLETE_ART
from .ui import say


def completion_summary(config: dict) -> None:
    print(COMPLETE_ART)
    say(f"Panel: https://{config['panel_domain']}", 'OK')
    say(f"Administrator: {config['admin']['username']} ({config['admin']['email']})", 'OK')
    say(f"Wings: {config['wing_domain']} — API port {config['wings_port']}, SFTP port {config['wings_sftp']}", 'OK')
    say(f"PHP runtime: {config['php_version']} | Scheduler: /etc/cron.d/pterodactyl (runs every minute)", 'OK')
    say('Services to check: systemctl status pteroq wings docker nginx', 'NOTE')
    say('Delete the Application API key you created: Panel → Administration → Application API → delete/revoke that key.', 'WARN')
    say('Keep the Wings DNS record DNS-only (not proxied by Cloudflare), and open game allocation ports separately.', 'WARN')