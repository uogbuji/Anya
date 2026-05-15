'''
Resend email provider. Default for Anya.

API: https://resend.com/docs/api-reference/emails/send-email

Env vars:
  RESEND_API_KEY   required
  RESEND_FROM      default sender, e.g. 'Anya <anya@yourdomain.com>'
'''

from __future__ import annotations

import os
from typing import Any

import httpx


API_URL = 'https://api.resend.com/emails'


async def send(
    *,
    to: list[str],
    subject: str,
    html: str,
    text: str | None = None,
    from_addr: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get('RESEND_API_KEY')
    from_addr = from_addr or os.environ.get('RESEND_FROM') or 'Anya <onboarding@resend.dev>'
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
