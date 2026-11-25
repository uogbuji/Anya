'''Unit tests for the LLM dispatcher's failure handling (no live providers).'''

import asyncio
import socket

import pytest

import anya.llm as llm
from anya.config import BackendConfig
from anya.llm import UpstreamAPIError, complete


def _closed_local_port() -> int:
    '''A localhost port with nothing listening (bind, read the port, release it).'''
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_call_budget_bounds_the_whole_call(monkeypatch):
    async def stalled(*args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(llm, '_openai', stalled)
    monkeypatch.setattr(llm, 'CALL_BUDGET', 0.2)
    backend = BackendConfig(name='slow', provider='openai', model='m')
    with pytest.raises(UpstreamAPIError, match=r'slow: no complete response within 0s'):
        asyncio.run(complete(backend, 'sys', 'user'))


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_connection_refused_is_upstream_error(monkeypatch, provider):
    # Regression: a refused connection (e.g. a local server that's down) escaped as a raw SDK error.
    # Also covers config base_url reaching the Anthropic client (it used to be ignored).
    monkeypatch.setattr(llm, 'MAX_RETRIES', 0)
    base_url = f'http://127.0.0.1:{_closed_local_port()}' + ('/v1' if provider == 'openai' else '')
    backend = BackendConfig(name='down', provider=provider, model='m', api_key='k', base_url=base_url)
    with pytest.raises(UpstreamAPIError, match='could not connect'):
        asyncio.run(complete(backend, 'sys', 'user'))


def test_strict_compatible_schemas():
    from anya.llm import strict_compatible

    strict = {'type': 'object', 'additionalProperties': False, 'required': ['ok', 'items'], 'properties': {
        'ok': {'type': 'boolean'},
        'items': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['url'],
            'properties': {'url': {'type': 'string'}}}},
    }}
    assert strict_compatible(strict)
    # Typical hand-written schemas: optional fields or open objects. Previously sent with
    # strict=True, which OpenAI rejects with HTTP 400.
    assert not strict_compatible({'type': 'object', 'properties': {'significant': {'type': 'boolean'}}})
    loose_inner = {**strict, 'properties': {**strict['properties'], 'items': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'url': {'type': 'string'}}}}}}
    assert not strict_compatible(loose_inner)


def test_token_limit_param_by_endpoint():
    from anya.llm import _token_limit_param

    def backend(url):
        return BackendConfig(name='b', provider='openai', model='m', base_url=url)

    assert _token_limit_param(backend(None)) == 'max_completion_tokens'
    assert _token_limit_param(backend('https://api.openai.com/v1')) == 'max_completion_tokens'
    assert _token_limit_param(backend('https://openrouter.ai/api/v1')) == 'max_tokens'
    assert _token_limit_param(backend('http://localhost:8080/v1')) == 'max_tokens'
