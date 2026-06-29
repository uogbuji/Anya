'''Unit tests for the job executor's environment wiring.'''

import os
from pathlib import Path

from anya.executor import _add_shared_lib_path


def test_add_shared_lib_path_when_lib_present(tmp_path: Path):
    '''A sibling `_lib/` puts the jobs-root on PYTHONPATH for `from _lib import ...`.'''
    (tmp_path / '_lib').mkdir()
    job_path = tmp_path / 'my-job'
    job_path.mkdir()

    env = _add_shared_lib_path({}, job_path)
    assert env['PYTHONPATH'] == str(tmp_path.resolve())


def test_add_shared_lib_path_absent(tmp_path: Path):
    '''No `_lib/` -> PYTHONPATH is left untouched.'''
    job_path = tmp_path / 'my-job'
    job_path.mkdir()

    env = _add_shared_lib_path({}, job_path)
    assert 'PYTHONPATH' not in env


def test_add_shared_lib_path_preserves_existing(tmp_path: Path):
    '''An existing PYTHONPATH is preserved, with the jobs-root prepended.'''
    (tmp_path / '_lib').mkdir()
    job_path = tmp_path / 'my-job'
    job_path.mkdir()

    env = _add_shared_lib_path({'PYTHONPATH': '/existing/path'}, job_path)
    assert env['PYTHONPATH'] == f'{tmp_path.resolve()}{os.pathsep}/existing/path'
