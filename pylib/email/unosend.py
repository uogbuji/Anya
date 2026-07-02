'''
Unosend email provider.

Secret (env): UNOSEND_API_KEY (required).
Sender comes from config.toml [email] from (passed in as from_addr); falls back to
'anya@localhost'.
'''

from __future__ import annotations

import os
from typing import Any

import httpx


API_URL = 'https://www.unosend.co/api/v1/emails'


async def send(
    *,
    to: list[str],
    subject: str,
    html: str,
    text: str | None = None,
    from_addr: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get('UNOSEND_API_KEY')
    from_addr = from_addr or 'anya@localhost'
    if not api_key:
        raise ValueError('UNOSEND_API_KEY required for the unosend email provider')

    payload: dict[str, Any] = {
        'from': from_addr,
        'to': to,
        'subject': subject,
        'html': html,
    }
    if text:
        payload['text'] = text

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            API_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
