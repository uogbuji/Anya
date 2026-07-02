'''Long-term memory for critical findings. Jobs can instruct updates.'''

from datetime import datetime
from pathlib import Path


def read_memory(memory_path: Path) -> str:
    '''Read current memory content.'''
    if not memory_path.exists():
        return ''
    return memory_path.read_text(encoding='utf-8')


def append_memory(memory_path: Path, job_id: str, content: str) -> None:
    '''
    Append to long-term memory. Used for critical findings per job instructions.
    '''
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().isoformat() + 'Z'
    block = f'\n---\n[{ts}] [{job_id}]\n{content}\n'
    with memory_path.open('a', encoding='utf-8') as f:
        f.write(block)


def prune_memory(memory_path: Path, resolved_description: str) -> None:
    '''
    Remove memory blocks that match the resolved description.
    Used when Claude outputs ---RESOLVED--- to indicate an issue is fixed.

    Blocks are removed if their content contains any phrase from the resolved
    description (split by comma, "and", "or"). Case-insensitive.
    '''
    if not memory_path.exists():
        return
    raw = memory_path.read_text(encoding='utf-8').strip()
    phrases = [
        p.strip().lower()
        for p in resolved_description.replace(' and ', ',').replace(' or ', ',').split(',')
        if len(p.strip()) > 4
    ]
    if not phrases:
        return
    blocks = []
    for part in raw.split('\n---\n'):
        part = part.strip()
        if not part or part == '---':
            continue
        # Skip if not a valid memory block (header format: [timestamp] [job_id])
        lines = part.split('\n', 1)
        first_line = lines[0]
        if '[' not in first_line or ']' not in first_line:
            continue
        content = (lines[1] if len(lines) > 1 else '').lower()
        if not any(phrase in content for phrase in phrases):
            blocks.append(part)
    new_content = '\n---\n'.join(blocks) if blocks else ''
    if new_content:
        new_content = new_content.strip()
        if not new_content.startswith('---'):
            new_content = '---\n' + new_content
    memory_path.write_text(new_content, encoding='utf-8')
