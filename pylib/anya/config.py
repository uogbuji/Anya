'''
Anya instance config: model alias registry + backend definitions.

Preferred backends are OpenRouter (cloud) and local OpenAI-compatible servers
(e.g. oMLX). Anthropic direct is supported but not the primary path.

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

    [models.backends.or-opus]
    provider = "openrouter"
    model = "anthropic/claude-opus-4.7"

    [models.backends.local-qwen]
    provider = "openai"              # oMLX is an OpenAI-compatible server
    model = "qwen3.6-mlx"
    base_url = "http://localhost:8080/v1"

If no config.toml is present, a single backend named "default" is synthesized
from the legacy env vars.
'''

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'


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


@dataclass
class AnyaConfig:
    '''Top-level Anya instance config.'''

    backends: dict[str, BackendConfig] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    default: str | None = None

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


def _backend_from_env() -> BackendConfig:
    '''Synthesize a single "default" backend from legacy env vars.'''
    provider = (os.environ.get('LLM_PROVIDER') or 'anthropic').lower()
    if provider == 'anthropic':
        return BackendConfig(
            name='default',
            provider='anthropic',
            model=os.environ.get('LLM_MODEL') or 'claude-sonnet-4-20250514',
            api_key=os.environ.get('ANTHROPIC_API_KEY'),
        )
    if provider == 'openrouter':
        return BackendConfig(
            name='default',
            provider='openai',
            model=os.environ.get('LLM_MODEL') or '',
            api_key=os.environ.get('OPENROUTER_API_KEY') or os.environ.get('LLM_API_KEY'),
            base_url=os.environ.get('LLM_BASE_URL') or OPENROUTER_BASE_URL,
        )
    if provider == 'openai':
        return BackendConfig(
            name='default',
            provider='openai',
            model=os.environ.get('LLM_MODEL') or '',
            api_key=os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY'),
            base_url=(
                os.environ.get('OPENAI_API_BASE')
                or os.environ.get('LLM_BASE_URL')
                or 'http://localhost:8080/v1'
            ),
        )
    raise ValueError(f'Unknown LLM_PROVIDER: {provider!r}. Use anthropic | openrouter | openai.')


def _expand_env(value: str | None) -> str | None:
    '''Allow ${ENV_VAR} substitution in backend strings.'''
    if value is None:
        return None
    return os.path.expandvars(value)


def load_config(path: Path | None = None) -> AnyaConfig:
    '''
    Load Anya config from a TOML file. If path is None, looks for
    $ANYA_CONFIG_FILE, then ./config.toml. If nothing is found, returns
    a config with a single env-derived "default" backend.
    '''
    if path is None:
        env_path = os.environ.get('ANYA_CONFIG_FILE')
        if env_path:
            path = Path(env_path)
        else:
            candidate = Path('config.toml')
            if candidate.exists():
                path = candidate

    if path is None or not path.exists():
        env_backend = _backend_from_env()
        return AnyaConfig(backends={env_backend.name: env_backend})

    with path.open('rb') as f:
        data = tomllib.load(f)

    models = data.get('models', {})
    backends_raw = models.get('backends', {})
    aliases = {str(k): str(v) for k, v in models.get('aliases', {}).items()}
    default = models.get('default')

    backends: dict[str, BackendConfig] = {}
    for name, spec in backends_raw.items():
        provider = str(spec.get('provider', '')).lower()
        if provider == 'openrouter':
            # Sugar: normalize to openai with OR defaults filled in.
            backends[name] = BackendConfig(
                name=name,
                provider='openai',
                model=str(spec.get('model', '')),
                api_key=(
                    _expand_env(spec.get('api_key'))
                    or os.environ.get('OPENROUTER_API_KEY')
                    or os.environ.get('LLM_API_KEY')
                ),
                base_url=_expand_env(spec.get('base_url')) or OPENROUTER_BASE_URL,
            )
            continue
        if provider not in ('anthropic', 'openai'):
            raise ValueError(
                f'Backend {name!r}: provider must be openrouter|openai|anthropic, got {provider!r}'
            )
        backends[name] = BackendConfig(
            name=name,
            provider=provider,
            model=str(spec.get('model', '')),
            api_key=_expand_env(spec.get('api_key')) or _default_api_key_env(provider),
            base_url=_expand_env(spec.get('base_url')),
        )

    if not backends:
        env_backend = _backend_from_env()
        backends[env_backend.name] = env_backend

    return AnyaConfig(backends=backends, aliases=aliases, default=default)


def _default_api_key_env(provider: str) -> str | None:
    '''Pick the default env var for an API key when not set explicitly.'''
    if provider == 'anthropic':
        return os.environ.get('ANTHROPIC_API_KEY')
    if provider == 'openai':
        return os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY')
    return None
