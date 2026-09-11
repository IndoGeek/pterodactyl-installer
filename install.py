#!/usr/bin/env python3
"""IndoGeek's interactive Pterodactyl Panel + Wings installer (Debian/Ubuntu)."""
from __future__ import annotations

import sys

from src.installer import main

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled. Completed changes were not rolled back.')
        sys.exit(130)