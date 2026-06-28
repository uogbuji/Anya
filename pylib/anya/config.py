'''
Anya instance config: the single source of truth for non-secret settings.

config.toml holds everything that is NOT a secret — model aliases/backends, email
recipients/provider/sender, fetcher knobs, and filesystem paths. Secrets (API keys)
live ONLY in the environment; a backend may *reference* one via ${ENV_VAR} expansion,
but a literal secret written into config.toml is flagged with a warning.

config.toml layout:

    [models]
    default = "fast"                 # alias used when inference() omits model=

    [models.aliases]
    cheapest = "local-qwen"
    fast = "or-haiku"
    best-reasoning = "or-opus"

    [models.backends.or-haiku]
    provider = "openrouter"          # sugar: openai-compat with OR base_url + OPENROUTER_API_KEY
    model = "anthropic/claude-haiku-4.5"

    [models.backends.local-qwen]
    provider = "openai"              # oMLX is an OpenAI-compatible server
    model = "qwen3.6-mlx"
    base_url = "http://localhost:8080/v1"

    [email]
    provider = "resend"              # was ANYA_EMAIL_PROVIDER
    to = ["you@example.com"]         # was ANYA_EMAIL_TO
    from = "Anya <anya@example.com>" # was RESEND_FROM / UNOSEND_FROM

    [fetch]
    crawl4ai_base_url = "http://localhost:11235"        # was CRAWL4AI_BASE_URL
    reddit_user_agent = "python:anya:0.2 (by /u/anya)"  # was REDDIT_USER_AGENT

    [paths]
    blotter = "data/blotter.txt"            # was BLOTTER_FILE
    memory = "data/memory.txt"
    http_cache = "data/http-cache.sqlite"   # was ANYA_HTTP_CACHE

    [blotter]
    lock_timeout = 30                       # was BLOTTER_LOCK_TIMEOUT

A config.toml with at least one [models.backends.*] is required: there is no
env-var fallback for defining a backend (start from config.example.toml).
'''

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import structlog


OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'

# Defaults for non-secret settings, kept here as the single source of truth. Each maps to a
# config.toml field; modules read these via get_config() rather than os.environ.
DEFAULT_REDDIT_USER_AGENT = 'python:anya:0.2 (by /u/anya)'
DEFAULT_CRAWL4AI_BASE_URL = 'http://localhost:11235'

# Field names that carry secrets. A literal (non-${VAR}) value in one of these is a smell:
# the secret ends up baked into config.toml instead of staying in the environment.
_SECRET_FIELDS = frozenset({'api_key'})
# Matches an env reference: $VAR or ${VAR}. A value WITHOUT one is treated as a literal.
_ENV_REF_RE = re.compile(r'\$\{?\w+\}?')


@dataclass(frozen=True)
class BackendConfig:
    '''
    Resolved backend definition for a single named model.

    provider is one of {'anthropic', 'openai'}. The 'openrouter' label is sugar
    in config.toml; it is normalized to provider='openai' with OR defaults filled
    in (base_url + OPENROUTER_API_KEY).
    '''

    name: str
    provider: str  # 'anthropic' | 'openai'
    model: str
    api_key: str | None = None
    base_url: str | None = None


@dataclass(frozen=True)
class EmailConfig:
    '''Non-secret email settings (the API key stays in the provider's env var).'''

    provider: str = 'resend'
    to: list[str] = field(default_factory=list)
    from_addr: str | None = None  # config key is `from`; renamed (reserved word)


@dataclass(frozen=True)
class FetchConfig:
    '''Non-secret fetcher knobs.'''

    crawl4ai_base_url: str = DEFAULT_CRAWL4AI_BASE_URL
    reddit_user_agent: str = DEFAULT_REDDIT_USER_AGENT


@dataclass(frozen=True)
class PathsConfig:
    '''Filesystem paths (CLI flags still override at the call site).'''

    blotter: str = 'data/blotter.txt'
    memory: str = 'data/memory.txt'
    http_cache: str = 'data/http-cache.sqlite'


@dataclass
class AnyaConfig:
    '''Top-level Anya instance config.'''

    backends: dict[str, BackendConfig] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    default: str | None = None
    email: EmailConfig = field(default_factory=EmailConfig)
    fetch: FetchConfig = field(default_factory=FetchConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    blotter_lock_timeout: float = 30.0

    def resolve(self, selector: str | None) -> BackendConfig:
        '''
        Resolve a selector (alias name or backend name) to a BackendConfig.

        If selector is None, falls back to self.default, then to any backend
        named "default", then errors.
        '''
        if selector is None:
            selector = self.default or 'default'

        # Walk alias chain (max 8 hops to catch cycles).
        seen: set[str] = set()
        cur = selector
        for _ in range(8):
            if cur in self.backends:
                return self.backends[cur]
            if cur in seen:
                raise ValueError(f'Alias cycle detected at {cur!r}')
            seen.add(cur)
            if cur in self.aliases:
                cur = self.aliases[cur]
                continue
            break
        raise ValueError(
            f'Unknown model selector {selector!r}. '
            f'Known backends: {sorted(self.backends)}; aliases: {sorted(self.aliases)}'
        )


def _expand_env(value: str | None) -> str | None:
    '''Allow ${ENV_VAR} substitution in backend strings.'''
    if value is None:
        return None
    return os.path.expandvars(value)


def _warn_literal_secret(backend: str, field_name: str, raw: str) -> None:
    '''Warn when a known-secret field holds a literal value instead of a ${VAR} reference.'''
    if raw and not _ENV_REF_RE.search(raw):
        structlog.get_logger().warning(
            'secret written literally in config.toml; reference an env var via ${VAR} instead',
            backend=backend, field=field_name)


def _default_api_key_env(provider: str) -> str | None:
    '''Per-provider secret env var used when a backend omits api_key.'''
    if provider == 'anthropic':
        return os.environ.get('ANTHROPIC_API_KEY')
    if provider == 'openai':
        return os.environ.get('OPENAI_API_KEY')
    return None


def _parse_backend(name: str, spec: dict) -> BackendConfig:
    '''Parse one [models.backends.*] table into a BackendConfig.'''
    raw_api_key = spec.get('api_key')
    if isinstance(raw_api_key, str):
        _warn_literal_secret(name, 'api_key', raw_api_key)

    provider = str(spec.get('provider', '')).lower()
    if provider == 'openrouter':
        # Sugar: normalize to openai with OR defaults filled in.
        return BackendConfig(
            name=name,
            provider='openai',
            model=str(spec.get('model', '')),
            api_key=_expand_env(raw_api_key) or os.environ.get('OPENROUTER_API_KEY'),
            base_url=_expand_env(spec.get('base_url')) or OPENROUTER_BASE_URL,
        )
    if provider not in ('anthropic', 'openai'):
        raise ValueError(
            f'Backend {name!r}: provider must be openrouter|openai|anthropic, got {provider!r}'
        )
    return BackendConfig(
        name=name,
        provider=provider,
        model=str(spec.get('model', '')),
        api_key=_expand_env(raw_api_key) or _default_api_key_env(provider),
        base_url=_expand_env(spec.get('base_url')),
    )


def _parse_email(data: dict) -> EmailConfig:
    section = data.get('email', {})
    to_raw = section.get('to', [])
    if isinstance(to_raw, str):  # tolerate a single string or a comma-separated one
        to = [e.strip() for e in to_raw.split(',') if e.strip()]
    else:
        to = [str(e).strip() for e in to_raw if str(e).strip()]
    return EmailConfig(
        provider=str(section.get('provider', 'resend')).lower(),
        to=to,
        from_addr=section.get('from'),
    )


def _parse_fetch(data: dict) -> FetchConfig:
    section = data.get('fetch', {})
    return FetchConfig(
        crawl4ai_base_url=str(section.get('crawl4ai_base_url', DEFAULT_CRAWL4AI_BASE_URL)),
        reddit_user_agent=str(section.get('reddit_user_agent', DEFAULT_REDDIT_USER_AGENT)),
    )


def _parse_paths(data: dict) -> PathsConfig:
    section = data.get('paths', {})
    defaults = PathsConfig()
    return PathsConfig(
        blotter=str(section.get('blotter', defaults.blotter)),
        memory=str(section.get('memory', defaults.memory)),
        http_cache=str(section.get('http_cache', defaults.http_cache)),
    )


def _resolve_config_path(path: Path | None) -> Path | None:
    '''Resolve the config path: explicit arg, then $ANYA_CONFIG_FILE, then ./config.toml.'''
    if path is not None:
        return path
    env_path = os.environ.get('ANYA_CONFIG_FILE')
    if env_path:
        return Path(env_path)
    candidate = Path('config.toml')
    return candidate if candidate.exists() else None


def load_config(path: Path | None = None) -> AnyaConfig:
    '''
    Load Anya config from a TOML file. If path is None, looks for $ANYA_CONFIG_FILE,
    then ./config.toml. A config file defining at least one [models.backends.*] is
    required — there is no env-var fallback for synthesizing a backend.
    '''
    resolved = _resolve_config_path(path)
    if resolved is None or not resolved.exists():
        raise ValueError(
            'No config.toml found. Anya needs a config file defining at least one '
            '[models.backends.*] (set $ANYA_CONFIG_FILE or put config.toml in the cwd). '
            'Start from config.example.toml.'
        )

    with resolved.open('rb') as f:
        data = tomllib.load(f)

    models = data.get('models', {})
    backends_raw = models.get('backends', {})
    aliases = {str(k): str(v) for k, v in models.get('aliases', {}).items()}
    default = models.get('default')

    backends = {name: _parse_backend(name, spec) for name, spec in backends_raw.items()}
    if not backends:
        raise ValueError(
            f'No [models.backends.*] defined in {resolved}. Define at least one backend '
            '(see config.example.toml).'
        )

    blotter_section = data.get('blotter', {})
    return AnyaConfig(
        backends=backends,
        aliases=aliases,
        default=default,
        email=_parse_email(data),
        fetch=_parse_fetch(data),
        paths=_parse_paths(data),
        blotter_lock_timeout=float(blotter_section.get('lock_timeout', 30.0)),
    )


_config_cache: AnyaConfig | None = None


def get_config(path: Path | None = None, *, reload: bool = False) -> AnyaConfig:
    '''
    Return the process-wide Anya config, loading (and caching) it on first use.

    This is the single way non-LLM modules (email, blotter, fetchers) read settings.
    The CLI primes the cache once at startup with the resolved config path; controller
    subprocesses resolve the same file via $ANYA_CONFIG_FILE. Pass reload=True to force
    a re-read (used by the CLI to prime, and by tests).
    '''
    global _config_cache
    if _config_cache is None or reload:
        _config_cache = load_config(path)
    return _config_cache
