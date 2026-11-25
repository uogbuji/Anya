'''Unit tests for the Reddit fetcher's pure URL handling and login-wall detection.'''

from anya.fetchers.reddit import _login_wall, _to_old_reddit, _to_rss


def test_login_wall_detected_from_final_url():
    url = 'https://old.reddit.com/login/?reason=lor2&dest=https%3A%2F%2Fold.reddit.com%2Fr%2FPython%2F'
    assert _login_wall(url) == 'Reddit login wall (redirected to /login, reason=lor2)'
    assert _login_wall('https://www.reddit.com/login') == 'Reddit login wall (redirected to /login)'


def test_ordinary_urls_are_not_walls():
    assert _login_wall('https://old.reddit.com/r/Python/') is None
    assert _login_wall('https://old.reddit.com/r/Python.rss') is None
    assert _login_wall('https://example.com/login') is None  # only Reddit's own login page


def test_url_rewrites():
    assert _to_old_reddit('https://www.reddit.com/r/RevOps/') == 'https://old.reddit.com/r/RevOps/'
    assert _to_rss('https://www.reddit.com/r/RevOps/search?q=hubspot') == \
        'https://old.reddit.com/r/RevOps/search.rss?q=hubspot'
