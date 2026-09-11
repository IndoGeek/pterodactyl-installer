# IndoGeek Pterodactyl Installation

An interactive installer for a new **Pterodactyl Panel 1.x and local Wings** deployment on Debian or Ubuntu. It uses official Panel, Wings, Composer, Docker, and Certbot downloads.

## Run it

Use a fresh supported server with DNS records already pointing to it. Log in over SSH, then:

```bash
cd /path/to/indogeek-pterodactyl-installer
sudo python3 install.py
```

The installer displays every command it runs and asks before every optional or material change. Do not run it on a host with an existing Panel directory. It intentionally refuses hosts that have both Apache and Nginx installed, because selecting one would risk disrupting existing sites.

## What it configures

- PHP 8.3, MariaDB, Redis, Composer, the current Panel release, a cron scheduler, and `pteroq` queue worker.
- An Nginx or Apache virtual host for the Panel FQDN. Existing single-server installations are reused; otherwise you choose the server.
- Existing Let's Encrypt certificates are reused. Missing certificates can be requested through Certbot after DNS validation.
- Docker, the current Wings binary, its systemd service, and optional Docker swap accounting (a reboot is required after GRUB changes).
- Optional UFW rules for SSH, 80, 443, the chosen Wings API/SFTP ports, and the `pterodactyl0` bridge.

## Important limits and safety notes

The script opens no game-server allocation ranges because the required ports vary by game. Add those ranges from the Panel after installation (or open them in UFW yourself). It creates one `25565` allocation as a visible starting point when it provisions a node.

Creating a node through the official Panel API requires an **Application API key**. Administrator email/password credentials are not a supported substitute, and the script will not bypass authentication by touching Panel internals. After Panel setup, create the key at **Administration → Application API**, give it read/write permission, then paste it when asked. The script creates the location/node, downloads the generated configuration into `/etc/pterodactyl/config.yml`, and enables Wings.

If Panel and Wings use the same hostname, Cloudflare's proxy must be disabled for Wings traffic. Use DNS-only mode for that record. If they use different FQDNs, create both DNS records before Certbot runs.

After completion, back up `APP_KEY` somewhere outside the server:

```bash
sudo grep APP_KEY /var/www/pterodactyl/.env
```

## Recovery

The installer does not roll back completed operations if it is interrupted. Inspect service status with:

```bash
sudo systemctl status pteroq nginx apache2 wings docker
sudo journalctl -u wings -u pteroq -e
```

For current upstream requirements and troubleshooting, consult the official [Panel documentation](https://pterodactyl.io/panel/1.0/getting_started.html) and [Wings documentation](https://pterodactyl.io/wings/1.0/installing.html).
