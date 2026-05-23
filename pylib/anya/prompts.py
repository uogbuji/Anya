'''
WordLoom-backed prompt loading for Anya.

A job's prompts live in a single WordLoom file (default: anya.loom.toml in the
job dir — `.loom.toml` suffix so editors pick up TOML syntax highlighting).
Keys in that file are the promptids passed to inference(); values are templates
rendered with the context dict provided at the call site.

WordLoom's file/dir/glob inclusion feature is enabled so a prompt entry can
pull in supporting text without the controller having to assemble it.
'''

from __future__ import annotations

import threading
from pathlib import Path

import wordloom


_cache: dict[Path, dict[str, wordloom.language_item]] = {}
_cache_lock = threading.Lock()


def load_prompts(path: Path) -> dict[str, wordloom.language_item]:
    '''
    Load (and cache) a WordLoom file. The cache is keyed by the resolved path.
    '''
    resolved = path.resolve()
    with _cache_lock:
        if resolved in _cache:
            return _cache[resolved]
        if not resolved.exists():
            raise FileNotFoundError(f'Prompts file not found: {resolved}')
        loom = wordloom.load(resolved, features={'file-inclusion'})
        _cache[resolved] = loom
        return loom


def render_prompt(path: Path, promptid: str, context: dict) -> str:
    '''
    Resolve a promptid against a loom file and render with the given context.
    '''
    loom = load_prompts(path)
    if promptid not in loom:
        raise KeyError(
            f'Prompt {promptid!r} not found in {path}. '
            f'Available keys: {sorted(loom.keys())}'
        )
    return loom[promptid].render(**context)
