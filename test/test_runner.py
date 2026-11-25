'''Unit tests for run_tick: per-job isolation and the combined report email.'''

import asyncio
import json
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


def test_job_runs_once_per_period_across_ticks(tmp_path, sent):
    # Regression: every tick (and every restart of `anya serve`) re-ran all daily jobs.
    jobs = tmp_path / 'job'
    jobs.mkdir()
    _job(jobs, 'daily-ok', 'print("ran")\n')
    _job(jobs, 'daily-fails', 'raise SystemExit(3)\n')
    runs = tmp_path / 'data' / 'job-runs.json'

    def tick(**kw):
        asyncio.run(run_tick(jobs, tmp_path / 'blotter.txt', tmp_path / 'memory.txt', ['me@example.com'],
                             runs_path=runs, **kw))

    tick()
    assert sent[-1]['subject'] == '[Anya] daily-fails, daily-ok'
    record = json.loads(runs.read_text())
    assert record['daily-ok']['status'] == 'ok' and record['daily-fails']['status'] == 'failed'

    tick()  # same day: nothing due, so no email
    assert len(sent) == 1

    tick(select_jobs={'daily-ok'})  # explicit selection still runs, and isn't recorded
    assert len(sent) == 2
    assert json.loads(runs.read_text()) == record
