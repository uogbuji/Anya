'''Unit tests for job discovery and filtering.'''

from datetime import datetime
from pathlib import Path

from anya.job.loader import (
    Job,
    discover_jobs,
    filter_by_job_ids,
    filter_by_phase,
    should_run_job,
)


def _job(job_id: str, *, phase: str = 'default', frequency: str = 'weekly') -> Job:
    path = Path(f'/tmp/{job_id}')
    return Job(
        id=job_id,
        path=path,
        title=job_id,
        description='',
        frequency=frequency,
        phase=phase,
        entry=path / 'controller.py',
        type='pymain',
        prompts=path / 'anya.loom.toml',
        env={},
        select=None,
    )


def test_filter_by_job_ids_select():
    jobs = [_job('a'), _job('b'), _job('c')]
    assert [j.id for j in filter_by_job_ids(jobs, select={'a', 'c'})] == ['a', 'c']


def test_filter_by_job_ids_exclude():
    jobs = [_job('a'), _job('b'), _job('c')]
    assert [j.id for j in filter_by_job_ids(jobs, exclude={'b'})] == ['a', 'c']


def test_filter_by_job_ids_select_and_exclude():
    jobs = [_job('a'), _job('b'), _job('c')]
    filtered = filter_by_job_ids(jobs, select={'a', 'b', 'c'}, exclude={'b'})
    assert [j.id for j in filtered] == ['a', 'c']


def test_filter_by_phase_and_job_ids():
    jobs = [_job('a', phase='default'), _job('b', phase='ignore'), _job('c', phase='default')]
    after_phase = filter_by_phase(jobs, {'default'})
    after_ids = filter_by_job_ids(after_phase, select={'a', 'b'})
    assert [j.id for j in after_ids] == ['a']


def test_should_run_job_weekly_not_monday():
    job = _job('weekly-job', frequency='weekly')
    tuesday = datetime(2026, 6, 9, 12, 0)  # Tuesday
    assert should_run_job(job, tuesday) is False


def test_discover_jobs_respects_layout(tmp_path: Path):
    for name in ('alpha', 'beta'):
        job_dir = tmp_path / name
        job_dir.mkdir()
        (job_dir / 'anya.toml').write_text('title = "x"\n')
        (job_dir / 'controller.py').write_text('print("ok")\n')
    jobs = discover_jobs(tmp_path)
    assert [j.id for j in jobs] == ['alpha', 'beta']


def test_discover_jobs_skips_underscore_shared_lib(tmp_path: Path):
    '''`_lib/` (and other `_`-prefixed dirs) are shared code, not jobs.'''
    job_dir = tmp_path / 'alpha'
    job_dir.mkdir()
    (job_dir / 'anya.toml').write_text('title = "x"\n')
    (job_dir / 'controller.py').write_text('print("ok")\n')

    # A shared-lib dir that even (mistakenly) carries an anya.toml must not be
    # discovered as a job.
    lib_dir = tmp_path / '_lib'
    lib_dir.mkdir()
    (lib_dir / 'anya.toml').write_text('title = "not a job"\n')
    (lib_dir / 'hunt.py').write_text('VALUE = 1\n')

    jobs = discover_jobs(tmp_path)
    assert [j.id for j in jobs] == ['alpha']
