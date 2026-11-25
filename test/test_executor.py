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


def test_run_controller_times_out_and_kills(tmp_path: Path):
    '''A controller that overruns its timeout is killed and surfaces as TimeoutError.'''
    import asyncio
    import time

    import pytest

    from anya.executor import _run_controller
    from anya.job.loader import load_job

    job_dir = tmp_path / 'slow'
    job_dir.mkdir()
    (job_dir / 'anya.toml').write_text('title = "slow"\n')
    (job_dir / 'controller.py').write_text('import time\ntime.sleep(30)\n')
    job = load_job(job_dir)

    start = time.monotonic()
    with pytest.raises(TimeoutError, match='exceeded 0.3s'):
        asyncio.run(_run_controller(job, {}, timeout=0.3))
    assert time.monotonic() - start < 5


def test_parse_blocks_keeps_text_around_blocks():
    # Regression: everything after the first marker was dropped from the report.
    from anya.executor import _parse_blocks

    out = 'Intro.\n---MEMORY---\nremember A\n---END MEMORY---\nMiddle.\n' \
          '---RESOLVED---\nissue B\n---END RESOLVED---\nOutro.\n---MEMORY---\nremember C\n---END MEMORY---\n'
    summary, memory, resolved = _parse_blocks(out)
    assert summary == 'Intro.\n\nMiddle.\n\nOutro.'
    assert memory == 'remember A\n\nremember C'
    assert resolved == 'issue B'


def test_parse_blocks_unterminated_marker_left_in_report():
    from anya.executor import _parse_blocks

    summary, memory, resolved = _parse_blocks('Report.\n---MEMORY---\nno end marker\nMore report.')
    assert memory is None and resolved is None
    assert 'More report.' in summary


def test_report_html_is_escaped():
    # Regression: report text went into the email HTML raw.
    from anya.executor import report_bodies

    html_body, text_body = report_bodies([('job<1>', 'see <img src="https://evil.example/t.gif"> & <a href="x">')])
    assert '<img' not in html_body and '<a href' not in html_body
    assert '&lt;img src=&quot;https://evil.example/t.gif&quot;&gt; &amp;' in html_body
    assert '<h2>Job: job&lt;1&gt;</h2>' in html_body
    assert '<img src="https://evil.example/t.gif">' in text_body  # plain-text part is untouched
