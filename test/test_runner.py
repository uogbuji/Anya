'''Unit tests for run_tick: per-job isolation and the combined report email.'''

import asyncio
from pathlib import Path

import pytest

from anya.config import get_config
from anya.email import _PROVIDERS, register_provider
from anya.runner import run_tick


def _job(root: Path, name: str, controller: str | None, toml: str = 'title = "t"\n'):
    d = root / name
    d.mkdir()
    (d / 'anya.toml').write_text(toml)
    if controller is not None:
        (d / 'controller.py').write_text(controller)


@pytest.fixture
def sent(tmp_path, monkeypatch):
    '''Prime a config whose email provider is an in-memory recorder; yield the sent messages.'''
    conf = tmp_path / 'config.toml'
    conf.write_text('[models.backends.b]\nprovider = "openai"\nmodel = "m"\n[email]\nprovider = "recorder"\n')
    get_config(conf, reload=True)
    messages: list[dict] = []

    async def recorder(**kwargs):
        messages.append(kwargs)
        return {}

    register_provider('recorder', recorder)
    yield messages
    _PROVIDERS.pop('recorder', None)


def test_broken_job_does_not_stop_the_others(tmp_path, sent):
    # Regression: one job's load error (here, a missing controller) aborted the whole tick.
    jobs = tmp_path / 'job'
    jobs.mkdir()
    _job(jobs, 'a-good', 'print("all <fine>")\n')
    _job(jobs, 'b-broken', None)
    _job(jobs, 'c-bad-toml', 'print(1)\n', toml='title = \n')

    asyncio.run(run_tick(jobs, tmp_path / 'blotter.txt', tmp_path / 'memory.txt', ['me@example.com']))

    assert len(sent) == 1
    msg = sent[0]
    assert msg['subject'] == '[Anya] b-broken, c-bad-toml, a-good'
    assert 'ERROR: job failed to load - FileNotFoundError' in msg['text']
    assert 'ERROR: job failed to load - TOMLDecodeError' in msg['text']
    assert 'all <fine>' in msg['text']
    assert 'all &lt;fine&gt;' in msg['html']
    assert '[a-good] all <fine>' in (tmp_path / 'blotter.txt').read_text()


def test_load_errors_respect_job_selection(tmp_path, sent):
    jobs = tmp_path / 'job'
    jobs.mkdir()
    _job(jobs, 'a-good', 'print("ok")\n')
    _job(jobs, 'b-broken', None)

    asyncio.run(run_tick(jobs, tmp_path / 'blotter.txt', tmp_path / 'memory.txt', ['me@example.com'],
                         select_jobs={'a-good'}))

    assert sent[0]['subject'] == '[Anya] a-good'
