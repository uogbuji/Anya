'''Unit tests for the shared HTTP cache's handling of an old hishel 1.x database.'''

import sqlite3

import structlog

from anya.fetchers._cache import _retire_hishel1_cache


def _make_db(path, create_sql: str):
    with sqlite3.connect(path) as conn:
        conn.execute(create_sql)


def test_hishel1_cache_is_moved_aside(tmp_path):
    db = tmp_path / 'http-cache.sqlite'
    _make_db(db, 'CREATE TABLE entries (id, cache_key, data, created_at, deleted_at)')
    (tmp_path / 'http-cache.sqlite-wal').write_bytes(b'')

    with structlog.testing.capture_logs() as logs:
        _retire_hishel1_cache(db)

    assert not db.exists()
    assert not (tmp_path / 'http-cache.sqlite-wal').exists()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 2 and all('.hishel1-' in n for n in names)
    assert any('hishel 1.x' in e['event'] for e in logs)


def test_current_or_unrelated_db_left_alone(tmp_path):
    db = tmp_path / 'http-cache.sqlite'
    _make_db(db, 'CREATE TABLE entries (id, cache_key, data, expires_at, last_accessed_at, '
                 'chunk_count, ttl_deadline, tti)')
    _retire_hishel1_cache(db)
    assert db.exists()

    other = tmp_path / 'other.sqlite'
    _make_db(other, 'CREATE TABLE something (x)')
    _retire_hishel1_cache(other)
    assert other.exists()


def test_missing_or_non_sqlite_file_is_fine(tmp_path):
    _retire_hishel1_cache(tmp_path / 'absent.sqlite')  # no error
    junk = tmp_path / 'junk.sqlite'
    junk.write_text('not a database')
    _retire_hishel1_cache(junk)
    assert junk.exists()
