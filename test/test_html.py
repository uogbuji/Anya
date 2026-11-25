'''Unit tests for the vendored HTML cleaning / HTML→Markdown module (anya.fetchers._html).'''

from anya.fetchers._html import clean_html, html2markdown


def _md(html: str) -> str:
    tree, _ = clean_html(html)
    return html2markdown(tree)


def test_stylesheet_display_none_removed():
    html = '''<html><head><style>h1.hidden { display: none; }</style></head><body>
<h1>Visible heading</h1><h1 class="hidden">Hidden heading</h1>
<p>The quick brown fox. <a href="http://example.org">Learn More</a>.</p></body></html>'''
    tree, removed = clean_html(html)
    md = html2markdown(tree)
    assert 'Visible heading' in md
    assert 'Hidden heading' not in md
    assert any('Hidden heading' in r for r in removed)


def test_grouped_selector_hides_each_match():
    html = '''<html><head><style>#page1 { display: block; } #page2, #page3 { display: none; }</style></head>
<body><div id="page1"><p>Page 1 text</p></div><div id="page2"><p>Page 2 text</p></div></body></html>'''
    md = _md(html)
    assert 'Page 1 text' in md
    assert 'Page 2 text' not in md


def test_inline_style_display_none_removed():
    # Regression: the original parsed inline styles as a stylesheet, so this survived.
    html = '''<div style="display: block"><p>Page 1 text</p></div>
<div style="display: none"><p>Page 2 text</p></div>
<span style="visibility:hidden">ghost</span>'''
    md = _md(html)
    assert 'Page 1 text' in md
    assert 'Page 2 text' not in md
    assert 'ghost' not in md


def test_nested_hidden_elements_removed_once():
    '''A hidden child inside a hidden parent is removed with the parent, not touched again.'''
    html = '''<style>.x { display: none; }</style>
<div class="x">outer<p class="x" aria-hidden="true">inner</p></div><p>kept</p>'''
    tree, removed = clean_html(html)
    assert html2markdown(tree) == 'kept'
    assert len([r for r in removed if 'outer' in r]) == 1
    assert not any(r == 'inner' for r in removed)  # child never processed separately


def test_aria_hidden_removed_but_tabindex_minus_one_kept():
    # Regression: the original removed tabindex="-1" elements, dropping whole <main> regions.
    html = '''<main tabindex="-1"><p>Main article text</p></main>
<div aria-hidden="true">decorative</div>'''
    md = _md(html)
    assert 'Main article text' in md
    assert 'decorative' not in md


def test_scripts_and_styles_removed():
    html = '<html><head><style>p { color: red; }</style></head><body><script>alert(1)</script><p>hi</p></body></html>'
    tree, removed = clean_html(html)
    assert html2markdown(tree) == 'hi'
    assert any('alert(1)' in r for r in removed)


def test_unparseable_css_is_tolerated():
    html = '<style>@@@ nonsense {{{ display: none</style><p>still here</p>'
    assert _md(html) == 'still here'


def test_html2markdown_structure():
    html = '''<html><head><title>Doc Title</title></head><body>
<h2>Section</h2>
<ul><li>one</li><li>two</li></ul>
<ol><li>first</li><li>second</li></ol>
<p><a href="https://example.com/x">a link</a></p>
<pre>  indented
code</pre>
<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
</body></html>'''
    md = html2markdown(html)  # accepts a raw string too
    assert md.startswith('# Doc Title')
    assert '## Section' in md
    assert '* one\n* two' in md
    assert '1. first\n2. second' in md
    assert '[a link](https://example.com/x)' in md
    assert '```\n  indented\ncode\n```' in md
    assert '| A | B |\n| --- | --- |\n| 1 | 2 |' in md


def test_comments_dropped_without_error():
    # Regression: lexbor yields comment nodes from iter(), and reading their attrs raised TypeError.
    html = '<!DOCTYPE html><html><body><!-- secret note --><div><!-- x --><p>visible</p></div></body></html>'
    assert _md(html) == 'visible'
    assert html2markdown(html) == 'visible'  # unclean input too
