'''
The inference() library call: the one entry point controllers use to ask an
LLM something. Text-in / text-or-JSON-out, no tool calls.

A controller process picks up its prompts file and config from env vars that
the executor sets before spawning it:

- ANYA_PROMPTS_FILE: path to the WordLoom prompts file
- ANYA_CONFIG_FILE: path to the Anya config.toml (optional)
- ANYA_JOB_ID, ANYA_JOB_PATH: informational, also passed through

Usage from a controller:

    from anya import inference

    text = await inference('summarize-page', context={'page': page_markdown})
    is_match = await inference(
        'significant-update-filter',
        context={'new_content': site.markdown},
        model='cheapest',
        response_schema={'type': 'object', 'properties': {'significant': {'type': 'boolean'}}},
    )
'''

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from anya.config import AnyaConfig, BackendConfig, get_config
from anya.llm import InferenceProtocolError, UpstreamAPIError, complete
from anya.prompts import render_prompt


DEFAULT_SYSTEM_PROMPT = (
    'You are a read-only analysis assistant. You produce text (or structured JSON when '
    'requested). You do NOT request tool calls and you do NOT take destructive actions. '
    'Follow the task in the user message exactly.'
)


def _augment_system_prompt(sys_prompt: str, now: date) -> str:
    '''
    Append the current date to the system prompt. Inference providers don't set
    it and the model's training prior guesses an earlier year, so any prompt that
    reasons about time (deadlines, "recent", relative dates) goes wrong without it.
    Making it ambient here means no job has to plumb the date into its prompts.
    '''
    return f'{sys_prompt}\nThe current date is {now.isoformat()}.'


def _get_config() -> AnyaConfig:
    '''Process-wide Anya config (delegates to the shared, cached accessor).'''
    return get_config()


def _prompts_path() -> Path:
    '''Resolve the prompts file path from env, falling back to <job>/anya.loom.toml.'''
    explicit = os.environ.get('ANYA_PROMPTS_FILE')
    if explicit:
        return Path(explicit)
    job_path = Path(os.environ.get('ANYA_JOB_PATH', '.'))
    return job_path / 'anya.loom.toml'


async def inference(
    promptid: str,
    context: dict[str, Any] | None = None,
    *,
    model: str | None = None,
    system: str | None = None,
    response_schema: dict | None = None,
    max_tokens: int = 4096,
    temperature: float | None = None,
    now: date | None = None,
    **extra: Any,
) -> str | dict:
    '''
    Run a single inference call.

    - promptid: WordLoom key in the job's prompts file
    - context:  template params for the prompt; consumed by str.format
    - model:    alias or backend name (resolved via config.toml). Optional;
                falls back to the config's [models] default, then to the
                synthesized "default" env-based backend.
    - system:   override the default safety/system prompt
    - response_schema: when given, the call returns a parsed JSON dict
    - now:      override "today" (defaults to date.today()); the current date is
                appended to the system prompt so prompts can reason about time.
                Pass a fixed date for deterministic tests/replay.
    - extra:    forbidden tool-call kwargs raise InferenceProtocolError;
                anything else is currently ignored
    '''
    context = context or {}
    cfg = _get_config()
    backend: BackendConfig = cfg.resolve(model)

    user = render_prompt(_prompts_path(), promptid, context)
    base_system = system if system is not None else DEFAULT_SYSTEM_PROMPT
    sys_prompt = _augment_system_prompt(base_system, now or date.today())

    return await complete(
        backend,
        sys_prompt,
        user,
        response_schema=response_schema,
        max_tokens=max_tokens,
        temperature=temperature,
        **extra,
    )


__all__ = ['inference', 'InferenceProtocolError', 'UpstreamAPIError']
