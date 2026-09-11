#!/usr/bin/env python3
"""Interactive, selective cleanup for an IndoGeek Pterodactyl installation."""
from __future__ import annotations

import sys

from src.uninstaller import main

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled; no rollback was attempted.')
        sys.exit(130)