'''
Pluggable email providers. Default: Resend (https://resend.com).

A provider is any async callable matching the EmailProvider protocol:

    async def send(*, to, subject, html, text=None, from_addr=None, api_key=None) -> dict

Built-in providers: 'resend' (default), 'unosend'. Selection:
1. The `provider=` arg to send_email(), if given.
2. `config.toml [email] provider`.
3. Falls back to 'resend'.

The sender address comes from `config.toml [email] from` (or the `from_addr` arg).
Only the API key is a secret and stays in env (RESEND_API_KEY / UNOSEND_API_KEY).

Register your own with register_provider('myprov', send_fn).
'''

from __future__ import annotations

from typing import Any, Protocol

from anya.config import get_config


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
    '''Resolve a provider name (explicit arg or config.toml) to (name, callable).'''
    _ensure_builtins_loaded()
    chosen = (name or get_config().email.provider or 'resend').lower()
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

    Non-secret settings (provider, sender) come from config.toml [email]; the
    provider's API key is read from its env var (RESEND_API_KEY / UNOSEND_API_KEY).
    Explicit args here override both.
    '''
    _, fn = resolve_provider(provider)
    return await fn(
        to=to,
        subject=subject,
        html=html,
        text=text,
        from_addr=from_addr or get_config().email.from_addr,
        api_key=api_key,
    )


__all__ = ['send_email', 'register_provider', 'resolve_provider', 'EmailProvider']
