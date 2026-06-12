'''
LLM provider abstraction. Supports Anthropic and OpenAI-compatible APIs
(including local oMLX deployments fronted as OpenAI-compatible servers).

The dispatcher accepts:
- system + user prompt text
- optional JSON schema for response_schema-constrained output
- standard params (max_tokens, temperature, ...)

Tool use is NOT exposed. Callers cannot pass tools=; the dispatcher refuses
to forward any tool/function-call kwarg. Inference is text-in / text-or-JSON-out.
'''

from __future__ import annotations

import json
from typing import Any

from anya.config import BackendConfig


_DISALLOWED_KWARGS = frozenset({
    'tools',
    'tool_choice',
    'functions',
    'function_call',
})


class InferenceProtocolError(Exception):
    '''Raised when a caller violates inference() invariants (e.g. passes tools=).'''


class UpstreamAPIError(Exception):
    '''
    Raised when the upstream LLM provider returns an error (HTTP non-2xx).
    Wraps the provider's response in a single concise message so a controller
    failure doesn't print a 50-line traceback into the user's email.
    '''


def _extract_provider_error(payload: Any) -> str:
    '''
    Walk a provider error payload (often nested for routers like OpenRouter)
    and return the most specific human-readable message we can find.
    '''
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return payload
    if isinstance(payload, dict):
        if 'error' in payload:
            inner = _extract_provider_error(payload['error'])
            if inner:
                return inner
        if 'message' in payload and isinstance(payload['message'], str):
            base = payload['message']
            meta = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else None
            if meta and 'raw' in meta:
                deeper = _extract_provider_error(meta['raw'])
                if deeper and deeper != base:
                    return f'{base} ({deeper})'
            return base
    return ''


def _wrap_openai_error(backend: BackendConfig, exc: Exception) -> UpstreamAPIError:
    '''Translate an openai.APIStatusError (or similar) into UpstreamAPIError.'''
    status = getattr(exc, 'status_code', None)
    body = getattr(exc, 'body', None) or getattr(exc, 'response', None)
    if hasattr(body, 'json'):
        try:
            body = body.json()
        except Exception:  # noqa: BLE001
            body = None
    msg = _extract_provider_error(body) or str(exc)
    where = backend.base_url or '(openai)'
    return UpstreamAPIError(f'{backend.name} via {where}: HTTP {status} — {msg}')


def _wrap_anthropic_error(backend: BackendConfig, exc: Exception) -> UpstreamAPIError:
    '''Translate an anthropic.APIStatusError into UpstreamAPIError.'''
    status = getattr(exc, 'status_code', None)
    body = getattr(exc, 'body', None)
    if hasattr(body, 'json'):
        try:
            body = body.json()
        except Exception:  # noqa: BLE001
            body = None
    msg = _extract_provider_error(body) or str(exc)
    return UpstreamAPIError(f'{backend.name} (anthropic): HTTP {status} — {msg}')


def _check_kwargs(extra: dict[str, Any]) -> None:
    '''Refuse tool-call related kwargs at dispatch time.'''
    bad = sorted(k for k in extra if k in _DISALLOWED_KWARGS)
    if bad:
        raise InferenceProtocolError(
            f'inference() refuses tool-call kwargs: {bad}. '
            'Anya inference is text-in/text-out by design.'
        )


async def complete(
    backend: BackendConfig,
    system: str,
    user: str,
    *,
    response_schema: dict | None = None,
    max_tokens: int = 4096,
    temperature: float | None = None,
    **extra: Any,
) -> str | dict:
    '''
    Run a single inference call. Returns str (when no schema) or dict (when schema given).

    On schema requests where the backend doesn't return parseable JSON, we retry
    once with a "your previous reply was not valid JSON" nudge, then raise.
    '''
    _check_kwargs(extra)

    if backend.provider == 'anthropic':
        return await _anthropic(backend, system, user, response_schema, max_tokens, temperature)
    if backend.provider == 'openai':
        return await _openai(backend, system, user, response_schema, max_tokens, temperature)
    raise ValueError(f'Unknown provider: {backend.provider!r}')


async def _anthropic(
    backend: BackendConfig,
    system: str,
    user: str,
    schema: dict | None,
    max_tokens: int,
    temperature: float | None,
) -> str | dict:
    from anthropic import APIStatusError, AsyncAnthropic

    client = AsyncAnthropic(api_key=backend.api_key)
    params: dict[str, Any] = {
        'model': backend.model,
        'max_tokens': max_tokens,
        'system': system,
        'messages': [{'role': 'user', 'content': user}],
    }
    if temperature is not None:
        params['temperature'] = temperature

    try:
        if schema is None:
            msg = await client.messages.create(**params)
            return msg.content[0].text

        # Schema requested → coerce via tool-use (Anthropic's native way to force JSON).
        tool_name = 'emit_result'
        tool = {
            'name': tool_name,
            'description': 'Emit the structured result.',
            'input_schema': schema,
        }
        msg = await client.messages.create(
            **params,
            tools=[tool],
            tool_choice={'type': 'tool', 'name': tool_name},
        )
    except APIStatusError as e:
        raise _wrap_anthropic_error(backend, e) from None

    for block in msg.content:
        if getattr(block, 'type', None) == 'tool_use' and getattr(block, 'name', None) == tool_name:
            return block.input
    raise InferenceProtocolError(
        f'Anthropic tool-use did not return a {tool_name} block; got: {msg.content!r}'
    )


async def _openai(
    backend: BackendConfig,
    system: str,
    user: str,
    schema: dict | None,
    max_tokens: int,
    temperature: float | None,
) -> str | dict:
    from openai import APIStatusError, AsyncOpenAI

    if not backend.model:
        raise ValueError(f'Backend {backend.name!r}: model is required for OpenAI-compatible provider')

    client = AsyncOpenAI(
        base_url=backend.base_url,
        api_key=backend.api_key or 'not-needed',
    )
    params: dict[str, Any] = {
        'model': backend.model,
        'max_tokens': max_tokens,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }
    if temperature is not None:
        params['temperature'] = temperature

    try:
        if schema is None:
            resp = await client.chat.completions.create(**params)
            return resp.choices[0].message.content or ''

        # Schema requested → ask for structured JSON. Many servers (including
        # grammar-capable oMLX builds) honor response_format json_schema. If a
        # backend ignores it, we fall back to one post-hoc parse-and-retry.
        schema_params = dict(params)
        schema_params['response_format'] = {
            'type': 'json_schema',
            'json_schema': {'name': 'result', 'schema': schema, 'strict': True},
        }
        resp = await client.chat.completions.create(**schema_params)
        raw = resp.choices[0].message.content or ''
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Retry once, more explicit about the JSON contract.
        nudge = f'{user}\n\nYour reply MUST be a single JSON object matching this schema:\n{json.dumps(schema)}'
        retry_params = dict(params)
        retry_params['messages'] = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': nudge},
        ]
        retry_params['response_format'] = schema_params['response_format']
        resp = await client.chat.completions.create(**retry_params)
        raw = resp.choices[0].message.content or ''
    except APIStatusError as e:
        raise _wrap_openai_error(backend, e) from None

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise InferenceProtocolError(
            f'Backend {backend.name!r} did not return valid JSON after retry. Raw: {raw[:500]!r}'
        ) from e
