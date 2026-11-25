'''
Resend email provider. Default for Anya.

API: https://resend.com/docs/api-reference/emails/send-email

Secret (env): RESEND_API_KEY (required).
Sender comes from config.toml [email] from (passed in as from_addr); falls back to
a Resend onboarding address.
'''

import os
from typing import Any

import httpx

from anya._http import client_or_new


API_URL = 'https://api.resend.com/emails'


async def send(
    *,
    to: list[str],
    subject: str,
    html: str,
    text: str | None = None,
    from_addr: str | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get('RESEND_API_KEY')
    from_addr = from_addr or 'Anya <onboarding@resend.dev>'
    if not api_key:
        raise ValueError('RESEND_API_KEY required for the resend email provider')

    payload: dict[str, Any] = {
        'from': from_addr,
        'to': to,
        'subject': subject,
        'html': html,
    }
    if text:
        payload['text'] = text

    async with client_or_new(client, lambda: httpx.AsyncClient(timeout=30.0)) as c:
        resp = await c.post(
            API_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
