# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Atlassian Document Format (Jira descriptions and comments) to editor HTML. All text is escaped."""

from datetime import datetime, timezone
from html import escape

BLOCK_TAGS = {
    "paragraph": "p",
    "blockquote": "blockquote",
    "bulletList": "ul",
    "orderedList": "ol",
    "listItem": "li",
    "tableRow": "tr",
}


def _attr(value):
    return escape(str(value or ""), quote=True)


def _marks(text, marks):
    html = escape(text)
    for mark in marks or []:
        kind = mark.get("type")
        attrs = mark.get("attrs") or {}
        if kind == "strong":
            html = f"<strong>{html}</strong>"
        elif kind == "em":
            html = f"<em>{html}</em>"
        elif kind == "underline":
            html = f"<u>{html}</u>"
        elif kind == "strike":
            html = f"<s>{html}</s>"
        elif kind == "code":
            html = f"<code>{html}</code>"
        elif kind == "subsup":
            tag = "sub" if attrs.get("type") == "sub" else "sup"
            html = f"<{tag}>{html}</{tag}>"
        elif kind == "link" and str(attrs.get("href", "")).startswith(("http://", "https://", "mailto:")):
            html = f'<a href="{_attr(attrs.get("href"))}" target="_blank" rel="noopener noreferrer">{html}</a>'
    return html


def _children(node, attachments):
    return "".join(_node(child, attachments) for child in node.get("content") or [])


def _node(node, attachments):
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    if kind == "text":
        return _marks(node.get("text", ""), node.get("marks"))
    if kind == "hardBreak":
        return "<br>"
    if kind == "doc":
        return _children(node, attachments)
    if kind in BLOCK_TAGS:
        tag = BLOCK_TAGS[kind]
        if tag == "ol" and attrs.get("order") not in (None, 1):
            return f'<ol start="{int(attrs["order"])}">{_children(node, attachments)}</ol>'
        return f"<{tag}>{_children(node, attachments)}</{tag}>"
    if kind == "heading":
        level = min(max(int(attrs.get("level") or 1), 1), 6)
        return f"<h{level}>{_children(node, attachments)}</h{level}>"
    if kind == "codeBlock":
        text = "".join(child.get("text", "") for child in node.get("content") or [] if isinstance(child, dict))
        language = attrs.get("language")
        lang = f' class="language-{_attr(language)}"' if language else ""
        return f"<pre><code{lang}>{escape(text)}</code></pre>"
    if kind == "rule":
        return "<hr>"
    if kind in ("panel", "expand", "nestedExpand"):
        title = attrs.get("title")
        heading = f"<p><strong>{escape(title)}</strong></p>" if title else ""
        return f"<blockquote>{heading}{_children(node, attachments)}</blockquote>"
    if kind == "table":
        return f"<table><tbody>{_children(node, attachments)}</tbody></table>"
    if kind in ("tableHeader", "tableCell"):
        tag = "th" if kind == "tableHeader" else "td"
        return f"<{tag}>{_children(node, attachments)}</{tag}>"
    if kind == "mention":
        return f"<strong>{escape(attrs.get('text') or '@someone')}</strong>"
    if kind == "emoji":
        return escape(attrs.get("text") or attrs.get("shortName") or "")
    if kind in ("inlineCard", "blockCard", "embedCard"):
        url = attrs.get("url") or ""
        if str(url).startswith(("http://", "https://")):
            return f'<a href="{_attr(url)}" target="_blank" rel="noopener noreferrer">{escape(url)}</a>'
        return ""
    if kind == "date":
        try:
            moment = datetime.fromtimestamp(int(attrs.get("timestamp")) / 1000, tz=timezone.utc)
            return escape(moment.strftime("%d %b %Y"))
        except (TypeError, ValueError):
            return ""
    if kind == "status":
        return f"<code>{escape(attrs.get('text') or '')}</code>"
    if kind in ("taskList", "decisionList"):
        return f"<ul>{_children(node, attachments)}</ul>"
    if kind in ("taskItem", "decisionItem"):
        box = "☑" if attrs.get("state") in ("DONE", "DECIDED") else "☐"
        return f"<li>{box} {_children(node, attachments)}</li>"
    if kind in ("mediaSingle", "mediaGroup"):
        return _children(node, attachments)
    if kind in ("media", "mediaInline"):
        name = attrs.get("alt") or attachments.get(str(attrs.get("id")), "") or "attachment"
        return f"<p><em>[Attachment: {escape(name)}]</em></p>"
    # unknown node: keep its text
    return _children(node, attachments)


def adf_to_html(document, attachments=None):
    """``document`` is an ADF dict (or a plain string from older Jira). Returns HTML ("<p></p>" when empty)."""
    if not document:
        return "<p></p>"
    if isinstance(document, str):
        paragraphs = [f"<p>{escape(line)}</p>" for line in document.splitlines() if line.strip()]
        return "".join(paragraphs) or "<p></p>"
    html = _node(document, attachments or {})
    return html or "<p></p>"
