'''Unit tests for config.py: the config/secret split and the get_config accessor.'''

import pytest
import structlog

from anya import config as cfgmod
from anya.config import get_config, load_config


def _write(tmp_path, text: str):
    p = tmp_path / 'config.toml'
    p.write_text(text, encoding='utf-8')
    return p


MINIMAL_BACKEND = '''
[models.backends.or-haiku]
provider = "openrouter"
model = "anthropic/claude-haiku-4.5"
'''


def test_parses_new_sections(tmp_path):
    p = _write(tmp_path, MINIMAL_BACKEND + '''
[email]
provider = "unosend"
to = ["a@x.com", "b@y.com"]
from = "Anya <anya@x.com>"

[fetch]
crawl4ai_base_url = "http://crawl4ai:11235"
reddit_user_agent = "custom-ua/1.0"

[paths]
blotter = "/srv/blotter.txt"
memory = "/srv/memory.txt"
http_cache = "/srv/cache.sqlite"

[blotter]
lock_timeout = 12.5
''')
    cfg = load_config(p)
    assert cfg.email.provider == 'unosend'
    assert cfg.email.to == ['a@x.com', 'b@y.com']
    assert cfg.email.from_addr == 'Anya <anya@x.com>'
    assert cfg.fetch.crawl4ai_base_url == 'http://crawl4ai:11235'
    assert cfg.fetch.reddit_user_agent == 'custom-ua/1.0'
    assert cfg.paths.blotter == '/srv/blotter.txt'
    assert cfg.paths.memory == '/srv/memory.txt'
    assert cfg.paths.http_cache == '/srv/cache.sqlite'
    assert cfg.blotter_lock_timeout == 12.5


def test_section_defaults_when_absent(tmp_path):
    '''A config with only a backend uses code defaults for every other section.'''
    cfg = load_config(_write(tmp_path, MINIMAL_BACKEND))
    assert cfg.email.provider == 'resend'
    assert cfg.email.to == []
    assert cfg.email.from_addr is None
    assert cfg.fetch.crawl4ai_base_url == cfgmod.DEFAULT_CRAWL4AI_BASE_URL
    assert cfg.fetch.reddit_user_agent == cfgmod.DEFAULT_REDDIT_USER_AGENT
    assert cfg.paths.blotter == 'data/blotter.txt'
    assert cfg.blotter_lock_timeout == 30.0


def test_email_to_tolerates_comma_string(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_BACKEND + '''
[email]
to = "a@x.com, b@y.com"
'''))
    assert cfg.email.to == ['a@x.com', 'b@y.com']


def test_missing_config_raises(tmp_path, monkeypatch):
    monkeypatch.delenv('ANYA_CONFIG_FILE', raising=False)
    monkeypatch.chdir(tmp_path)  # no ./config.toml here
    with pytest.raises(ValueError, match='No config.toml found'):
        load_config(None)


def test_no_backends_raises(tmp_path):
    p = _write(tmp_path, '[email]\nprovider = "resend"\n')
    with pytest.raises(ValueError, match='No \\[models.backends'):
        load_config(p)


def test_literal_secret_warns(tmp_path):
    p = _write(tmp_path, '''
[models.backends.b]
provider = "anthropic"
model = "claude-haiku-4-5-20251001"
api_key = "sk-thisIsALiteralSecret"
''')
    with structlog.testing.capture_logs() as logs:
        load_config(p)
    assert any('literally' in e.get('event', '') for e in logs), logs


def test_env_referenced_secret_does_not_warn(tmp_path):
    p = _write(tmp_path, '''
[models.backends.b]
provider = "anthropic"
model = "claude-haiku-4-5-20251001"
api_key = "${ANTHROPIC_API_KEY}"
''')
    with structlog.testing.capture_logs() as logs:
        load_config(p)
    assert not any('literally' in e.get('event', '') for e in logs), logs


def test_get_config_caches_and_reloads(tmp_path):
    p = _write(tmp_path, MINIMAL_BACKEND)
    first = get_config(p, reload=True)
    assert get_config() is first              # cached: same object, no path needed
    second = get_config(p, reload=True)       # forced reload: fresh object
    assert second is not first
