"""Minimal Pterodactyl Application API client and a tiny YAML emitter."""
from __future__ import annotations

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def api(base: str, key: str, method: str, endpoint: str, payload=None):
    req = Request(base.rstrip('/') + '/api/application' + endpoint, method=method,
                  # Cloudflare often blocks Python's default ``Python-urllib``
                  # signature before the request can reach the Panel API.
                  headers={'Authorization': f'Bearer {key}', 'Accept': 'Application/vnd.pterodactyl.v1+json',
                           'Content-Type': 'application/json',
                           'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'},
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
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines += [f'{pad}{k}:', yaml_dump(v, indent + 2)]
            else:
                lines.append(f'{pad}{k}: {yaml_scalar(v)}')
        return '\n'.join(lines)
    if isinstance(obj, list):
        return '\n'.join(f'{pad}- {yaml_scalar(v)}' if not isinstance(v, (dict, list)) else f'{pad}-\n{yaml_dump(v, indent + 2)}' for v in obj)
    return pad + yaml_scalar(obj)


def yaml_scalar(v):
    if v is None:
        return 'null'
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v))


def find_by_attribute(response: dict, attribute: str, value):
    """Return the first matching item from a standard Pterodactyl API list."""
    for item in response.get('data', []):
        attributes = item.get('attributes', {})
        if attributes.get(attribute) == value:
            return attributes
    return None