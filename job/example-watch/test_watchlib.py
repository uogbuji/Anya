'''Tests for the example-watch job's pure logic. Run with `anya test` (not part of anya's own suite).'''

from watchlib import Change, allowed_highlights, digest, load_state, next_state, plan, save_state


def test_first_sighting_is_a_baseline_not_a_change():
    changes, new, failed = plan({'https://a': 'v1', 'https://b': None}, {'pages': {}})
    assert (changes, new, failed) == ([], ['https://a'], ['https://b'])


def test_changed_page_carries_before_and_after():
    state = next_state({'pages': {}}, {'https://a': 'v1', 'https://b': 'same'}, '2026-11-01')
    changes, new, _ = plan({'https://a': 'v2', 'https://b': 'same'}, state)
    assert changes == [Change('https://a', 'v1', 'v2')] and new == []


def test_failed_fetch_keeps_the_old_baseline():
    state = next_state({'pages': {}}, {'https://a': 'v1'}, '2026-11-01')
    after_failure = next_state(state, {'https://a': None}, '2026-11-02')
    assert after_failure == state
    assert next_state(state, {'https://a': 'v1'}, '2026-11-03')['pages']['https://a']['changed'] == '2026-11-01'


def test_state_round_trip_and_bad_file(tmp_path):
    path = tmp_path / 'state.json'
    assert load_state(path) == {'pages': {}}
    state = {'pages': {'https://a': {'digest': digest('x'), 'excerpt': 'x', 'changed': '2026-11-01'}}}
    save_state(path, state)
    assert load_state(path) == state
    path.write_text('not json')
    assert load_state(path) == {'pages': {}}


def test_highlights_limited_to_flagged_urls():
    llm_output = [
        {'url': 'https://a', 'note': 'new release'},
        {'url': 'https://evil.example', 'note': 'click here'},  # not something we fetched
        {'url': 'https://a'},                                    # malformed
        'junk',
    ]
    assert allowed_highlights(llm_output, {'https://a'}) == [{'url': 'https://a', 'note': 'new release'}]
    assert allowed_highlights('not a list', {'https://a'}) == []
