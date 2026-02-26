'''Send email via Unosend API.'''

import os

import httpx

UNOSEND_API = 'https://www.unosend.co/api/v1/emails'


async def send_email(
    to: list[str],
    subject: str,
    html: str,
    text: str | None = None,
    from_addr: str | None = None,
    api_key: str | None = None,
) -> dict:
    '''
    Send email via Unosend. Uses UNOSEND_API_KEY and UNOSEND_FROM env if not passed.
    '''
    api_key = api_key or os.environ.get('UNOSEND_API_KEY')
    from_addr = from_addr or os.environ.get('UNOSEND_FROM', 'anya@localhost')
    if not api_key:
        raise ValueError('UNOSEND_API_KEY required')
    payload = {
        'from': from_addr,
        'to': to,
        'subject': subject,
        'html': html,
    }
    if text:
        payload['text'] = text
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            UNOSEND_API,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
