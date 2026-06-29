'''
Unit tests for the search ("SERP") fetchers — offline and deterministic.

Cover the pure pieces (provider-response normalization + markdown rendering) and
the no-key soft-fail. Anything that hits the live Tavily/Brave APIs is an
integration test and lives elsewhere (network + secrets, excluded from this run).
'''

import asyncio

from anya.fetchers.search import (
    BraveSearchFetcher,
    TavilySearchFetcher,
    _parse_brave,
    _parse_tavily,
    _results_to_markdown,
    create_searcher,
)


def test_parse_tavily_normalizes_results():
    data = {'results': [
        {'title': 'Acme hiring RevOps', 'url': 'https://acme.example/jobs', 'content': 'HubSpot admin wanted'},
        {'title': 'Beta Co', 'url': 'https://beta.example', 'content': ''},
        'junk',  # tolerated/skipped
    ]}
    out = _parse_tavily(data)
    assert out == [
        {'title': 'Acme hiring RevOps', 'url': 'https://acme.example/jobs', 'snippet': 'HubSpot admin wanted'},
        {'title': 'Beta Co', 'url': 'https://beta.example', 'snippet': ''},
    ]


def test_parse_tavily_empty():
    assert _parse_tavily({}) == []


def test_parse_brave_normalizes_results():
    data = {'web': {'results': [
        {'title': 'RevOps thread', 'url': 'https://reddit.example/r/revops', 'description': 'hubspot tips'},
    ]}}
    out = _parse_brave(data)
    assert out == [{'title': 'RevOps thread', 'url': 'https://reddit.example/r/revops', 'snippet': 'hubspot tips'}]


def test_parse_brave_missing_web_key():
    assert _parse_brave({}) == []


def test_results_to_markdown_emits_urls_verbatim():
    md = _results_to_markdown('revops hubspot', [
        {'title': 'Acme', 'url': 'https://acme.example/jobs/revops', 'snippet': 'hiring'},
        {'title': '', 'url': 'https://beta.example', 'snippet': ''},
    ])
    assert '# Search results for: revops hubspot' in md
    # URLs appear verbatim so the controller's URL allow-list can match them.
    assert 'https://acme.example/jobs/revops' in md
    assert 'https://beta.example' in md
    assert '## Acme' in md and '## (untitled)' in md
    assert 'hiring' in md


def test_tavily_no_key_soft_fails(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    fetcher = TavilySearchFetcher(max_results=5)  # explicit count avoids config load
    result = asyncio.run(fetcher.search('anything'))
    assert result.success is False
    assert 'TAVILY_API_KEY' in (result.error or '')
    assert result.markdown == ''


def test_brave_no_key_soft_fails(monkeypatch):
    monkeypatch.delenv('BRAVE_API_KEY', raising=False)
    fetcher = BraveSearchFetcher(max_results=5)
    result = asyncio.run(fetcher.search('anything'))
    assert result.success is False
    assert 'BRAVE_API_KEY' in (result.error or '')


def test_create_searcher_dispatch():
    assert isinstance(create_searcher('tavily', max_results=1), TavilySearchFetcher)
    assert isinstance(create_searcher('brave', max_results=1), BraveSearchFetcher)
    try:
        create_searcher('nope')
        assert False, 'expected ValueError'
    except ValueError:
        pass
