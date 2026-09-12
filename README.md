# IndoGeek Pterodactyl Installation

An interactive installer for a new **Pterodactyl Panel 1.x and local Wings** deployment on Debian or Ubuntu. It uses official Panel, Wings, Composer, Docker, and Certbot downloads.

## Project layout

```
.
├── install.sh          # Global entry point: installs Python deps, then runs install.py
├── uninstall.sh        # Global entry point: installs Python deps, then runs uninstall.py
├── install.py          # Thin entry wrapper (implementation lives in src/)
├── uninstall.py        # Thin entry wrapper (implementation lives in src/)
├── src/
│   ├── installer.py    # Install orchestration / main
│   ├── uninstaller.py  # Uninstall orchestration / main
│   ├── config.py       # Central paths (state, logs, host paths)
│   ├── log.py          # Timestamped log-file setup
│   ├── ui.py           # Prompts / messages (mirrored to the log)
│   ├── utils.py        # run/capture/installed/root checks/remove_path
│   ├── state.py        # Resume state (save/load/clear)
│   ├── manifest.py     # Uninstall manifest
│   ├── packages.py     # apt helpers + tracked installed packages
│   ├── php.py          # PHP version selection/socket detection
│   ├── database.py     # MariaDB database/user creation
│   ├── panel.py        # Panel download, .env, scheduler, pteroq
│   ├── webserver.py    # Nginx/Apache config + ACME webroot site
│   ├── certbot.py      # Let's Encrypt certificates
│   ├── wings.py        # Docker + Wings binary/service
│   ├── apiclient.py    # Pterodactyl Application API + YAML emitter
│   ├── node.py         # Node provisioning through the Panel API
│   ├── firewall.py     # Optional UFW rules
│   ├── summary.py      # Completion summary
│   └── art.py          # ASCII banners
├── state/              # Temporary resume state + uninstall manifest (git-ignored)
└── logs/               # Every install/uninstall runs append a timestamped log
```

## Run it

Use a fresh supported server with DNS records already pointing to it. Log in over SSH, then:

```bash
cd /path/to/indogeek-pterodactyl-installer
sudo ./install.sh
```

The wrapper scripts are runnable from any directory, re-exec themselves through `sudo`, and install Python 3 (the only runtime dependency; the Python code itself uses only the standard library) via `apt-get` when it is missing or older than 3.8. After the install, run removal with:

```bash
sudo ./uninstall.sh
```

Each run appends a timestamped log under `logs/` (e.g. `install-20260911-221422.log`, `uninstall-...log`). You can also invoke the Python scripts directly:

```bash
sudo python3 install.py
sudo python3 uninstall.py
```

The installer displays every command it runs and asks before every optional or material change. Do not run it on a host with an existing Panel directory. It intentionally refuses hosts that have both Apache and Nginx installed, because selecting one would risk disrupting existing sites.

## What it configures

- A supported installed PHP runtime (preferring 8.3, then 8.2), MariaDB, Redis, Composer, the current Panel release, Pterodactyl's every-minute scheduler, and the `pteroq` queue worker. If neither supported PHP version is installed, it installs PHP 8.3 and only the required versioned packages.
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

The completed installation records uninstall metadata (domains, web server, PHP version, package list, database names, generated files — never credentials) in `state/manifest.json`, which `uninstall.sh` reads. `uninstall.py` asks separately before removing Panel files, Wings, services, web configuration, certificates, database data, the recorded PHP version, dependencies, Composer, and Docker resources. It never removes other PHP versions.

## Recovery and state

The installer saves its progress and supplied configuration in `state/state.json` (inside this project, git-ignored, root-only permissions). If it exits or is interrupted, run `sudo ./install.sh` again and it resumes after the last completed phase. When the Panel phase was not completed it reconfirms the administrator details; an account already present in the database from a previous install (e.g. a manual teardown that left the database behind) is removed and recreated with the new details. On a successful finish the temporary state file is removed automatically — the `state/` directory itself is kept for the manifest and future runs.

The installer does not roll back completed operations. Inspect service status with:

```bash
sudo systemctl status pteroq nginx apache2 wings docker
sudo journalctl -u wings -u pteroq -e
```

### Repair HTTPS after a resumed install

Resuming the installer re-runs the web-server phase, which rewrites the Panel site to plain HTTP. If the Let's Encrypt certificate already exists, the SSL phase is skipped and the HTTPS server block is lost, leaving the Panel openable only over HTTP while `APP_URL` still points at `https://...`.

Re-apply the existing certificate to the Panel site without starting a new install:

```bash
cd /path/to/indogeek-pterodactyl-installer
sudo ./install.sh repair-ssl
```

This is safe to run from a second SSH session in another terminal while the original installer is still running and waiting for the Application API key. It rewrites the Nginx/Apache site with an HTTPS server block and reloads the web server, then you can continue with the running install from the other terminal. The command fails loudly if no certificate exists yet, rather than enabling a broken HTTPS site.

For current upstream requirements and troubleshooting, consult the official [Panel documentation](https://pterodactyl.io/panel/1.0/getting_started.html) and [Wings documentation](https://pterodactyl.io/wings/1.0/installing.html).