'''
Pluggable email providers. Default: Resend (https://resend.com).

A provider is any async callable matching the EmailProvider protocol:

    async def send(*, to, subject, html, text=None, from_addr=None, api_key=None) -> dict

Built-in providers: 'resend' (default), 'unosend'. Selection:
1. The `provider=` arg to send_email(), if given.
2. The `ANYA_EMAIL_PROVIDER` env var.
3. Falls back to 'resend'.

Register your own with register_provider('myprov', send_fn).
'''

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Protocol


class EmailProvider(Protocol):
    async def __call__(
        self,
        *,
        to: list[str],
        subject: str,
        html: str,
        text: str | None = None,
        from_addr: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]: ...


_PROVIDERS: dict[str, EmailProvider] = {}


def register_provider(name: str, fn: EmailProvider) -> None:
    '''Register an email provider under a short name.'''
    _PROVIDERS[name] = fn


def _ensure_builtins_loaded() -> None:
    '''Lazy-import built-in providers on first dispatch.'''
    if 'resend' not in _PROVIDERS:
        from anya.email.resend import send as resend_send
        register_provider('resend', resend_send)
    if 'unosend' not in _PROVIDERS:
        from anya.email.unosend import send as unosend_send
        register_provider('unosend', unosend_send)


def resolve_provider(name: str | None = None) -> tuple[str, EmailProvider]:
    '''Resolve a provider name (env or explicit) to (name, callable).'''
    _ensure_builtins_loaded()
    chosen = (name or os.environ.get('ANYA_EMAIL_PROVIDER') or 'resend').lower()
    if chosen not in _PROVIDERS:
        raise ValueError(
            f'Unknown email provider {chosen!r}. Registered: {sorted(_PROVIDERS)}'
        )
    return chosen, _PROVIDERS[chosen]


async def send_email(
    to: list[str],
    subject: str,
    html: str,
    text: str | None = None,
    from_addr: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    '''
    Send an email via the configured (or explicit) provider.

    Provider-specific env vars (e.g. RESEND_API_KEY, RESEND_FROM) are read by
    each provider's send function; explicit args here override env.
    '''
    _, fn = resolve_provider(provider)
    return await fn(
        to=to,
        subject=subject,
        html=html,
        text=text,
        from_addr=from_addr,
        api_key=api_key,
    )


__all__ = ['send_email', 'register_provider', 'resolve_provider', 'EmailProvider']
