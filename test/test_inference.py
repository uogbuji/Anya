'''Unit tests for the inference() library call.'''

import asyncio
import importlib
from datetime import date

# Grab the submodule explicitly: `anya.__init__` rebinds the name `anya.inference`
# to the inference() function, so `import anya.inference as inf` yields the
# function, not the module. importlib returns the actual module object.
inf = importlib.import_module('anya.inference')


def test_augment_system_prompt_appends_date():
    out = inf._augment_system_prompt('BASE PROMPT', date(2026, 6, 23))
    assert out == 'BASE PROMPT\nThe current date is 2026-06-23.'


def test_inference_injects_current_date_into_system_prompt(monkeypatch):
    '''The model is told today's date, so a near deadline can't read as a year out.'''
    captured: dict = {}

    async def fake_complete(backend, sys_prompt, user, **kwargs):
        captured['system'] = sys_prompt
        captured['user'] = user
        return 'ok'

    class _Cfg:
        def resolve(self, model):
            return object()

    # Patch anya's own boundaries (config / prompt rendering / completion).
    monkeypatch.setattr(inf, '_get_config', lambda: _Cfg())
    monkeypatch.setattr(inf, 'render_prompt', lambda *a, **k: 'USER PROMPT')
    monkeypatch.setattr(inf, 'complete', fake_complete)

    result = asyncio.run(inf.inference('some-prompt', now=date(2026, 6, 23)))

    assert result == 'ok'
    assert 'The current date is 2026-06-23.' in captured['system']
    # the default safety prompt is preserved alongside the date
    assert inf.DEFAULT_SYSTEM_PROMPT in captured['system']


def test_inference_date_augments_custom_system_prompt(monkeypatch):
    captured: dict = {}

    async def fake_complete(backend, sys_prompt, user, **kwargs):
        captured['system'] = sys_prompt
        return 'ok'

    class _Cfg:
        def resolve(self, model):
            return object()

    monkeypatch.setattr(inf, '_get_config', lambda: _Cfg())
    monkeypatch.setattr(inf, 'render_prompt', lambda *a, **k: 'USER')
    monkeypatch.setattr(inf, 'complete', fake_complete)

    asyncio.run(inf.inference('p', system='Custom system.', now=date(2026, 1, 2)))

    assert captured['system'] == 'Custom system.\nThe current date is 2026-01-02.'
