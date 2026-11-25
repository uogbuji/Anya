'''
WordLoom-backed prompt loading for Anya.

A job's prompts live in a single WordLoom file (default: anya.loom.toml in the
job dir — `.loom.toml` suffix so editors pick up TOML syntax highlighting).
Keys in that file are the promptids passed to inference(); values are templates
rendered with the context dict provided at the call site.

WordLoom's file/dir/glob inclusion feature is enabled so a prompt entry can
pull in supporting text without the controller having to assemble it.

Anya's own prompts (e.g. the default system prompt) live in the package, under
anya/resources/; see package_prompt().
'''

from functools import lru_cache
from pathlib import Path

import wordloom

RESOURCES_DIR = Path(__file__).parent / 'resources'


@lru_cache(maxsize=32)
def _load(path: Path, mtime_ns: int) -> dict[str, wordloom.language_item]:
    # mtime_ns is part of the cache key only: editing the file yields a fresh load.
    return wordloom.load(path, features={'file-inclusion'})


def load_prompts(path: Path) -> dict[str, wordloom.language_item]:
    '''Load (and cache) a WordLoom file, reloading it if it has changed on disk.'''
    resolved = path.resolve()
    try:
        mtime_ns = resolved.stat().st_mtime_ns
    except FileNotFoundError:
        raise FileNotFoundError(f'Prompts file not found: {resolved}') from None
    return _load(resolved, mtime_ns)


def _section_keys(items: dict[str, wordloom.language_item]) -> list[str]:
    '''
    WordLoom indexes each item twice, by section name and by body text; keep only
    the names, so an error message doesn't dump every prompt body.
    '''
    return sorted(k for k, v in items.items() if k != str(v))


def render_prompt(path: Path, promptid: str, context: dict) -> str:
    '''Resolve a promptid against a loom file and render with the given context.'''
    loom = load_prompts(path)
    if promptid not in loom:
        raise KeyError(f'Prompt {promptid!r} not found in {path}. Available: {_section_keys(loom)}')
    return loom[promptid].render(**context)


def package_prompt(name: str, promptid: str, context: dict | None = None) -> str:
    '''Render one of anya's own packaged prompts (anya/resources/<name>.loom.toml).'''
    return render_prompt(RESOURCES_DIR / f'{name}.loom.toml', promptid, context or {}).strip()
