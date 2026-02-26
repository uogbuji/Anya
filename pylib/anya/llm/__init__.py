'''
LLM provider abstraction. Supports Anthropic (Claude) and OpenAI-compatible APIs.

Progressive capability:
- anthropic: Full support; future features (tools, extended thinking) when added.
- openai: Core text-in/text-out; no Anthropic-specific features.
'''

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class LLMConfig:
    '''Configuration for LLM calls.'''

    provider: str  # 'anthropic' | 'openai'
    model: str
    api_key: str | None = None
    base_url: str | None = None  # For openai: e.g. http://localhost:8080/v1

    @classmethod
    def from_env(cls, provider: str | None = None, model: str | None = None) -> LLMConfig:
        '''Build config from env vars.'''
        prov = (provider or os.environ.get('LLM_PROVIDER') or 'anthropic').lower()
        if prov == 'anthropic':
            return cls(
                provider='anthropic',
                model=model or os.environ.get('LLM_MODEL') or 'claude-sonnet-4-20250514',
                api_key=os.environ.get('ANTHROPIC_API_KEY'),
            )
        if prov == 'openai':
            return cls(
                provider='openai',
                model=model or os.environ.get('LLM_MODEL') or '',
                api_key=os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY'),
                base_url=os.environ.get('OPENAI_API_BASE') or os.environ.get('LLM_BASE_URL') or 'http://localhost:8080/v1',
            )
        raise ValueError(f'Unknown LLM provider: {prov}. Use anthropic or openai.')


async def call_llm(system: str, user_content: str, config: LLMConfig) -> str:
    '''
    Call the configured LLM. Returns the assistant text.
    '''
    if config.provider == 'anthropic':
        return await _call_anthropic(system, user_content, config)
    if config.provider == 'openai':
        return await _call_openai(system, user_content, config)
    raise ValueError(f'Unknown provider: {config.provider}')


async def _call_anthropic(system: str, user_content: str, config: LLMConfig) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.api_key)
    msg = await client.messages.create(
        model=config.model,
        max_tokens=4096,
        system=system,
        messages=[{'role': 'user', 'content': user_content}],
    )
    return msg.content[0].text


async def _call_openai(system: str, user_content: str, config: LLMConfig) -> str:
    from openai import AsyncOpenAI

    if not config.model:
        raise ValueError('LLM_MODEL required for OpenAI-compatible provider (e.g. mistral, Llama-3.2-1B)')
    client = AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key or 'not-needed',  # Local servers often skip auth
    )
    resp = await client.chat.completions.create(
        model=config.model,
        max_tokens=4096,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_content},
        ],
    )
    return resp.choices[0].message.content or ''
