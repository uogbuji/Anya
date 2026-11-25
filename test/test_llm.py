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
