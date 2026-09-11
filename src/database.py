"""Local MariaDB database and user creation for the Panel."""
from __future__ import annotations

import subprocess


def create_database(name: str, user: str, password: str) -> None:
    # Credentials travel through stdin/arguments only to the local MariaDB root socket; quote safely in SQL.
    def q(s: str) -> str:
        return "'" + s.replace('\\', '\\\\').replace("'", "''") + "'"

    sql = (f'CREATE DATABASE IF NOT EXISTS `{name.replace("`", "``")}`; '
           f'CREATE USER IF NOT EXISTS {q(user)}@\'127.0.0.1\' IDENTIFIED BY {q(password)}; '
           f'GRANT ALL PRIVILEGES ON `{name.replace("`", "``")}`.* TO {q(user)}@\'127.0.0.1\'; '
           f'FLUSH PRIVILEGES;')
    subprocess.run(['mariadb', '-e', sql], check=True)