'''Unit tests for job due-ness and the job run record (anya.job.runs).'''

import json
from datetime import date, datetime, timedelta

import pytest

from anya.job.runs import ANCHORS, is_due, last_run_date, load_runs, normalize_frequency, record_run

# 2026-11-23 is a Monday
MON, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 11, 23) + timedelta(days=i) for i in range(7))
NEXT_MON = MON + timedelta(days=7)


@pytest.mark.parametrize('freq, today, anchor', [
    ('daily', WED, WED),
    ('weekday', WED, WED), ('weekday', SAT, FRI), ('weekday', SUN, FRI),
    ('weekly', MON, MON), ('weekly', SUN, MON),
    ('saturday', SAT, SAT), ('saturday', FRI, SAT - timedelta(days=7)), ('saturday', SUN, SAT),
    ('sunday', SUN, SUN), ('sunday', SAT, SUN - timedelta(days=7)),
])
def test_anchor_is_most_recent_scheduled_date(freq, today, anchor):
    assert ANCHORS[freq](today) == anchor


def test_no_record_means_scheduled_days_only():
    '''Without a record, the old rule applies: run on the job's scheduled days.'''
    assert is_due('weekly', MON, None)
    assert not is_due('weekly', TUE, None)
    assert is_due('weekday', FRI, None) and not is_due('weekday', SAT, None)
    assert is_due('daily', THU, None)


def test_drift_past_midnight_no_longer_skips_a_weekly_job():
    # Regression: tick Sunday 23:50 + 24h + 15 min of job runtime = Tuesday 00:05, so the
    # Monday-only check never saw a Monday. Now the missed run catches up on Tuesday.
    last_weekly_run = MON - timedelta(days=7)
    assert is_due('weekly', TUE, last_weekly_run)


def test_repeat_ticks_and_restarts_do_not_rerun():
    assert not is_due('daily', WED, WED)
    assert not is_due('weekly', THU, MON)
    assert is_due('weekly', NEXT_MON, MON)
    assert is_due('daily', THU, WED)


def test_frequency_aliases_and_unknowns():
    assert normalize_frequency(' Sundays ') == 'sunday'
    assert normalize_frequency('weekdays') == 'weekday'
    assert normalize_frequency('monday') == 'weekly'
    with pytest.raises(ValueError, match='unknown frequency'):
        normalize_frequency('fortnightly')


def test_record_round_trip(tmp_path):
    path = tmp_path / 'data' / 'job-runs.json'
    runs = load_runs(path)
    assert runs == {}
    when = datetime(2026, 11, 24, 9, 30).astimezone()
    record_run(path, runs, 'alpha', when, 'ok')
    record_run(path, runs, 'beta', when, 'failed')
    loaded = load_runs(path)
    assert loaded['beta']['status'] == 'failed'
    assert last_run_date(loaded, 'alpha') == date(2026, 11, 24)
    assert last_run_date(loaded, 'missing') is None
    assert not (tmp_path / 'data' / 'job-runs.json.tmp').exists()


def test_unreadable_record_is_ignored(tmp_path):
    path = tmp_path / 'job-runs.json'
    path.write_text('{not json')
    assert load_runs(path) == {}
    path.write_text(json.dumps(['wrong', 'shape']))
    assert load_runs(path) == {}
    assert last_run_date({'x': {'last_run': 'garbage'}}, 'x') is None
