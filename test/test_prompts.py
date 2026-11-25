'''Unit tests for prompt loading and anya's packaged prompts.'''

import os

import pytest

from anya.prompts import package_prompt, render_prompt


def test_missing_prompt_lists_section_names_only(tmp_path):
    # Regression: the KeyError listed every prompt body (WordLoom indexes items by body too).
    loom = tmp_path / 'p.loom.toml'
    loom.write_text("lang = 'en'\n[greet]\n_ = '''Hello {name}, a long prompt body'''\n_m = ['name']\n")
    with pytest.raises(KeyError) as err:
        render_prompt(loom, 'nope', {})
    assert "Available: ['greet']" in str(err.value)
    assert 'long prompt body' not in str(err.value)


def test_edited_prompt_file_is_reloaded(tmp_path):
    loom = tmp_path / 'p.loom.toml'
    loom.write_text("lang = 'en'\n[p]\n_ = '''v1'''\n")
    assert render_prompt(loom, 'p', {}) == 'v1'
    loom.write_text("lang = 'en'\n[p]\n_ = '''v2'''\n")
    st = loom.stat()
    os.utime(loom, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))  # make the change visible
    assert render_prompt(loom, 'p', {}) == 'v2'


def test_packaged_system_prompt_ships_with_the_package():
    text = package_prompt('inference', 'inference-sysprompt')
    assert text.startswith('You are a read-only analysis assistant.')
