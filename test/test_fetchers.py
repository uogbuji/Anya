'''
Fetcher, searcher, and email-provider behavior over httpx.MockTransport: offline and
deterministic. Each component takes an injected client, so nothing is patched.
'''

import asyncio
import json

import httpx
import pytest

from anya.email.resend import send as resend_send
from anya.fetchers import (
    BraveSearchFetcher,
    Crawl4AIFetcher,
    RedditFetcher,
    RSSFetcher,
    SimpleHttpFetcher,
    TavilySearchFetcher,
)

RSS_BODY = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Feed T</title>
<item><title>First post</title><link>https://ex.example/1</link><description>&lt;b&gt;Hello&lt;/b&gt; world</description></item>
</channel></rss>'''


def mock_client(handler, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_plain_fetch_converts_html():
    def handler(request):
        return httpx.Response(200, html='<html><head><title>T</title></head><body><h1>Hi</h1>'
                                        '<p style="display:none">hidden</p><p>Body</p></body></html>')

    result = run(SimpleHttpFetcher(client=mock_client(handler)).fetch('https://ex.example/'))
    assert result.success and result.title == 'T'
    assert result.markdown == '# T\n\n# Hi\n\nBody'


def test_plain_fetch_http_error_is_soft_failure():
    result = run(SimpleHttpFetcher(client=mock_client(lambda r: httpx.Response(404))).fetch('https://ex.example/x'))
    assert not result.success and '404' in result.error


def test_plain_fetch_verifies_tls_by_default():
    # Regression: every plain fetch disabled certificate checks (verify=False).
    assert SimpleHttpFetcher().verify is True


def test_rss_fetcher_summarizes_feed():
    result = run(RSSFetcher(client=mock_client(lambda r: httpx.Response(200, content=RSS_BODY))).fetch('https://f/'))
    assert result.success and result.title == 'Feed T'
    assert '## First post\nhttps://ex.example/1\nHello world' in result.markdown


def test_reddit_fetch_html_with_user_agent():
    seen = {}

    def handler(request):
        seen['host'], seen['ua'] = request.url.host, request.headers['user-agent']
        return httpx.Response(200, html='<title>r/Python</title><p>posts</p>')

    result = run(RedditFetcher(user_agent='anya-test/1', client=mock_client(handler))
                 .fetch('https://www.reddit.com/r/Python/'))
    assert result.success and result.title == 'r/Python'
    assert seen == {'host': 'old.reddit.com', 'ua': 'anya-test/1'}


def test_reddit_login_wall_fails_on_both_paths():
    def handler(request):
        if request.url.path.startswith('/login'):
            return httpx.Response(200, html='<title>Welcome to Reddit</title>')
        return httpx.Response(302, headers={'location': 'https://old.reddit.com/login/?reason=lor2'})

    result = run(RedditFetcher(user_agent='ua', client=mock_client(handler, follow_redirects=True))
                 .fetch('https://old.reddit.com/r/Python/'))
    assert not result.success
    assert result.error.count('Reddit login wall (redirected to /login, reason=lor2)') == 2


def test_reddit_blocked_html_falls_back_to_rss():
    def handler(request):
        if request.url.path.endswith('.rss'):
            return httpx.Response(200, content=RSS_BODY)
        return httpx.Response(403)

    result = run(RedditFetcher(user_agent='ua', client=mock_client(handler)).fetch('https://old.reddit.com/r/x/'))
    assert result.success and result.url == 'https://old.reddit.com/r/x.rss'
    assert result.title == 'Feed T' and 'First post' in result.markdown


def test_crawl4ai_extracts_markdown():
    def handler(request):
        assert request.url == 'http://c4a:11235/crawl'
        assert json.loads(request.content)['urls'] == ['https://ex.example/']
        return httpx.Response(200, json={'success': True, 'results': [
            {'markdown': {'raw_markdown': '# Page'}, 'title': 'Page'}]})

    result = run(Crawl4AIFetcher(base_url='http://c4a:11235/', client=mock_client(handler))
                 .fetch('https://ex.example/'))
    assert result.success and result.markdown == '# Page' and result.title == 'Page'


def test_tavily_search_sends_key_and_renders_results():
    def handler(request):
        body = json.loads(request.content)
        assert body['api_key'] == 'tv-key' and body['query'] == 'revops' and body['max_results'] == 3
        return httpx.Response(200, json={'results': [{'title': 'A', 'url': 'https://a.example', 'content': 'snip'}]})

    result = run(TavilySearchFetcher(api_key='tv-key', max_results=3, client=mock_client(handler)).search('revops'))
    assert result.success and 'https://a.example' in result.markdown and 'snip' in result.markdown


def test_brave_search_http_error_is_soft_failure():
    def handler(request):
        assert request.headers['x-subscription-token'] == 'br-key'
        return httpx.Response(429)

    result = run(BraveSearchFetcher(api_key='br-key', max_results=3, client=mock_client(handler)).search('q'))
    assert not result.success and '429' in result.error


def test_resend_posts_email():
    sent = {}

    def handler(request):
        sent['auth'] = request.headers['authorization']
        sent['body'] = json.loads(request.content)
        return httpx.Response(200, json={'id': 'msg-1'})

    out = run(resend_send(to=['me@example.com'], subject='S', html='<p>h</p>', text='t',
                          from_addr='Anya <a@example.com>', api_key='re-key', client=mock_client(handler)))
    assert out == {'id': 'msg-1'}
    assert sent['auth'] == 'Bearer re-key'
    assert sent['body'] == {'from': 'Anya <a@example.com>', 'to': ['me@example.com'], 'subject': 'S',
                            'html': '<p>h</p>', 'text': 't'}


def test_resend_error_raises():
    with pytest.raises(httpx.HTTPStatusError):
        run(resend_send(to=['x@example.com'], subject='S', html='h', api_key='k',
                        client=mock_client(lambda r: httpx.Response(422))))


def test_custom_fetcher_registration():
    from anya.fetchers import FetchResult, create_fetcher, register_fetcher
    from anya.fetchers.protocol import FETCHERS

    class Echo:
        def __init__(self, prefix=''):
            self.prefix = prefix

        async def fetch(self, url):
            return FetchResult(url=url, markdown=self.prefix + url)

    register_fetcher('echo', Echo)
    try:
        assert run(create_fetcher('echo', prefix='> ').fetch('u')).markdown == '> u'
    finally:
        FETCHERS.pop('echo')
    with pytest.raises(ValueError, match=r"Unknown fetcher type 'echo'. Registered: \['crawl4ai', 'plain'"):
        create_fetcher('echo')
