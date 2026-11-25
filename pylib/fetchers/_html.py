# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
'''
HTML cleaning and HTML→Markdown conversion for the page fetchers.

############################################################################
# TEMPORARY VENDORED COPY. This module is adapted from OgbujiPT's
# `ogbujipt.text.html` (clean_html / html2markdown), and is planned to move
# into Amara. Once a released Amara provides it, delete this module, depend
# on Amara instead, and switch the imports in fetchers/protocol.py and
# fetchers/reddit.py. Keep changes here minimal in the meantime.
############################################################################

Changes from the OgbujiPT original:
- Uses selectolax's lexbor backend (`selectolax.lexbor`). selectolax 1.0 removed
  the Modest backend (`selectolax.parser`) the original imports.
- Inline `style="display: none"` is parsed as a declaration (`cssutils.parseStyle`);
  the original parsed it as a stylesheet, so inline-hidden content was never removed.
- Hidden elements are removed in one top-down pass that never visits the
  descendants of a removed node, rather than decomposing nodes from a flat list
  that still holds their (already destroyed) children.
- Drops HTML comments (lexbor's iter() yields them, and they have no attributes).
- No longer removes `tabindex="-1"` elements. Sites commonly put that on the main
  content container (a skip-link target), so the rule dropped whole pages.
- Drops the chunking/token helpers and backward-compatibility shims anya doesn't use.
'''

import logging
import re

import cssutils
from selectolax.lexbor import LexborHTMLParser, LexborNode

# cssutils logs every CSS rule it can't parse at ERROR level, which floods job
# output when cleaning real-world pages.
logging.getLogger('CSSUTILS').setLevel(logging.CRITICAL)

_HIDDEN_MARK = 'data-anya-hidden'  # set on nodes matched by a hiding stylesheet rule


def _hides(style) -> bool:
    '''Whether a cssutils style declaration hides its element.'''
    return 'none' in style.getPropertyValue('display') or 'hidden' in style.getPropertyValue('visibility')


def _is_hidden(node: LexborNode) -> bool:
    '''Whether a node is hidden by a stylesheet rule, its own style attribute, or aria-hidden.'''
    attrs = node.attrs
    if _HIDDEN_MARK in attrs or attrs.get('aria-hidden') == 'true':
        return True
    inline = attrs.get('style')
    return bool(inline) and _hides(cssutils.parseStyle(inline))


def _mark_stylesheet_hidden(tree: LexborHTMLParser) -> None:
    '''Mark every element that a `<style>` rule hides with display:none / visibility:hidden.'''
    for style_elem in tree.css('style'):
        sheet = cssutils.parseString(style_elem.text(deep=True, separator='', strip=False))
        for rule in sheet:
            if rule.type != rule.STYLE_RULE or not _hides(rule.style):
                continue
            selector = rule.selectorText
            if '::' in selector or ':after' in selector or ':before' in selector:
                continue
            try:
                matches = tree.css(selector)
            except Exception:  # noqa: BLE001 — selector lexbor can't evaluate; skip the rule
                continue
            for elem in matches:
                elem.attrs[_HIDDEN_MARK] = '1'


def clean_html(html: str) -> tuple[LexborHTMLParser, list[str]]:
    '''
    Parse HTML and remove content a reader wouldn't see: scripts, styles, and
    elements hidden by stylesheet rules, inline styles, or aria-hidden.

    Returns (tree, removed_content), where removed_content holds the text of
    each removed element.
    '''
    tree = LexborHTMLParser(html)
    removed: list[str] = []
    _mark_stylesheet_hidden(tree)

    # Top-down: once a node is removed, its descendants are never touched.
    stack = [tree.root] if tree.root else []
    while stack:
        node = stack.pop()
        for child in list(node.iter()):
            if not child.is_element_node:  # comments etc.: invisible, and they have no attrs
                child.decompose()
            elif child.tag in ('script', 'style') or _is_hidden(child):
                removed.append(child.text(deep=True, separator='', strip=False))
                child.decompose()
            else:
                stack.append(child)
    return tree, removed


def html2markdown(root: LexborHTMLParser | LexborNode | str) -> str:
    '''
    Convert HTML text or a parsed selectolax tree to Markdown, using simplified logic.
    Preserves indentation in code blocks, as does the inspiring code:
    https://github.com/SivilTaram/code-html-to-markdown/blob/main/main.py
    '''
    if isinstance(root, str):
        root = LexborHTMLParser(root)
    body = getattr(root, 'body', None) or root  # a parsed document has .body; a node is its own root
    chunks: list[str] = []
    if body:
        title_elem = root.css_first('title')
        if title_elem:
            title_text = title_elem.text(deep=True, separator='', strip=True)
            if title_text:
                chunks.append(f'# {title_text}\n\n')
        _process_element_to_markdown(body, chunks)
    return post_processing(''.join(chunks))


def _process_element_to_markdown(elem, chunks: list[str], level: int = 0) -> None:
    '''Recursively convert an HTML element to Markdown, appending to chunks.'''
    if not elem or not hasattr(elem, 'tag') or not getattr(elem, 'is_element_node', True):
        return  # comments and other non-element nodes carry no visible content

    tag = elem.tag.lower() if elem.tag else ''
    text = elem.text(deep=False, separator='', strip=True) if hasattr(elem, 'text') else ''

    match tag:
        case 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6':
            if text:
                chunks.append(f'\n{"#" * int(tag[1])} {text}\n\n')
        case 'p':
            if text:
                chunks.append(f'{text}\n\n')
        case 'strong' | 'b':
            if text:
                chunks.append(f'**{text}**')
        case 'em' | 'i':
            if text:
                chunks.append(f'*{text}*')
        case 'code':
            parent_tag = elem.parent.tag.lower() if elem.parent and hasattr(elem.parent, 'tag') else ''
            if parent_tag != 'pre' and text:  # code inside pre is handled by the pre case
                chunks.append(f'`{text}`')
        case 'pre':
            code_text = elem.text(deep=True, separator='\n', strip=False)
            if code_text:
                chunks.append(f'\n```\n{code_text}\n```\n\n')
            return  # children already captured
        case 'a':
            href = elem.attrs.get('href', '') if hasattr(elem, 'attrs') else ''
            link_text = elem.text(deep=True, separator='', strip=True)
            if link_text:
                chunks.append(f'[{link_text}]({href})' if href else link_text)
        case 'ul':
            chunks.append('\n')
            for child in elem.iter():
                if child != elem and hasattr(child, 'tag') and child.tag.lower() == 'li':
                    _process_element_to_markdown(child, chunks, level + 1)
            chunks.append('\n')
            return
        case 'ol':
            chunks.append('\n')
            idx = 1
            for child in elem.iter():
                if child != elem and hasattr(child, 'tag') and child.tag.lower() == 'li':
                    li_text = child.text(deep=True, separator='', strip=True)
                    if li_text:
                        chunks.append(f'{idx}. {li_text}\n')
                    idx += 1
            chunks.append('\n')
            return
        case 'li':
            li_text = elem.text(deep=True, separator='', strip=True)
            if li_text:
                chunks.append(f'* {li_text}\n')
        case 'blockquote':
            quote_text = elem.text(deep=True, separator='\n', strip=True)
            if quote_text:
                chunks.extend(f'> {line}\n' for line in quote_text.split('\n'))
                chunks.append('\n')
        case 'table':
            rows = elem.css('tr')
            if rows:
                header_cells = rows[0].css('th, td')
                if header_cells:
                    header_texts = [cell.text(deep=True, separator='', strip=True) for cell in header_cells]
                    chunks.append('\n| ' + ' | '.join(header_texts) + ' |\n')
                    chunks.append('| ' + ' | '.join(['---'] * len(header_texts)) + ' |\n')
                for row in rows[1:]:
                    cells = row.css('td')
                    if cells:
                        cell_texts = [cell.text(deep=True, separator='', strip=True) for cell in cells]
                        chunks.append('| ' + ' | '.join(cell_texts) + ' |\n')
                chunks.append('\n')
            return
        case 'div' | 'span' | 'section' | 'article' | 'main' | 'body':
            # Containers: just process children, with spacing for top-level blocks
            if tag in ('div', 'section', 'article') and level == 0:
                chunks.append('\n')
        case 'script' | 'style' | 'head' | 'meta':
            return
        case _:
            if text:  # unknown tags: just extract text
                chunks.append(text)

    for child in elem.iter():
        if child != elem:
            _process_element_to_markdown(child, chunks, level + 1)


def post_processing(markdown_content: str) -> str:
    '''Collapse whitespace-only lines and runs of blank lines; tidy spacing around inline code.'''
    markdown_content = '\n'.join(re.sub(r'^\s+$', '', line) for line in markdown_content.split('\n'))
    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
    markdown_content = re.sub(r'` \.', '`.', markdown_content)
    markdown_content = re.sub(r'` \,', '`,', markdown_content)
    return markdown_content.strip()
