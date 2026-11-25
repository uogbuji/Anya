'''Unit tests for long-term memory: parsing, job-scoped pruning, reading, locking.'''

import pytest

from anya.config import get_config
from anya.memory import (
    MemoryEntry,
    append_memory,
    format_memory,
    parse_memory,
    prune_memory,
    read_memory,
    resolved_phrases,
)


@pytest.fixture(autouse=True)
def _config(tmp_path):
    '''Locks read their timeout from config; prime a minimal one.'''
    conf = tmp_path / 'config.toml'
    conf.write_text('[models.backends.b]\nprovider = "openai"\nmodel = "m"\n')
    get_config(conf, reload=True)


def _seed(path):
    append_memory(path, 'grants', 'NSF portal login is broken\n---\nmarkdown rule kept in content')
    append_memory(path, 'grants', 'Deadline for XYZ fund moved to March')
    append_memory(path, 'news', 'NSF portal login is broken for news too')


def test_round_trip_keeps_content_with_rules(tmp_path):
    path = tmp_path / 'memory.txt'
    _seed(path)
    preamble, entries = parse_memory(path.read_text())
    assert preamble == ''
    assert [e.job_id for e in entries] == ['grants', 'grants', 'news']
    assert entries[0].content == 'NSF portal login is broken\n---\nmarkdown rule kept in content'
    assert parse_memory(format_memory(preamble, entries)) == (preamble, entries)


def test_prune_only_touches_the_resolving_job(tmp_path):
    # Regression: phrases were split on ",", " and ", " or " and matched any job's entries,
    # so a vague RESOLVED block could wipe most of memory.
    path = tmp_path / 'memory.txt'
    _seed(path)
    removed = prune_memory(path, '- nsf portal login is broken\n- done', 'grants')
    assert removed == 1
    _, entries = parse_memory(path.read_text())
    assert [(e.job_id, e.content[:12]) for e in entries] == [('grants', 'Deadline for'), ('news', 'NSF portal l')]


def test_resolved_phrases_are_whole_lines():
    assert resolved_phrases('* Deadline moved and portal fixed, finally\nok\n') == \
        ['deadline moved and portal fixed, finally']


def test_unrecognized_text_survives_a_prune(tmp_path):
    # Regression: prune dropped anything that didn't look like an entry.
    path = tmp_path / 'memory.txt'
    path.write_text('Hand-written notes at the top\n')
    append_memory(path, 'grants', 'resolve me please')
    prune_memory(path, 'resolve me please', 'grants')
    assert path.read_text() == 'Hand-written notes at the top\n'


def test_read_memory_from_env_and_by_job(tmp_path, monkeypatch):
    path = tmp_path / 'memory.txt'
    _seed(path)
    monkeypatch.setenv('ANYA_MEMORY_FILE', str(path))
    assert 'for news too' in read_memory()
    own = read_memory(job_id='grants')
    assert 'XYZ fund' in own and 'news too' not in own
    monkeypatch.delenv('ANYA_MEMORY_FILE')
    assert read_memory() == ''


def test_format_memory_entry_layout():
    text = format_memory('', [MemoryEntry('2026-11-24T00:00:00Z', 'j', 'c')])
    assert text == '\n---\n[2026-11-24T00:00:00Z] [j]\nc\n'
