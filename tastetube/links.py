"""Find YouTube video IDs in Hacker News comment HTML, and clean the comment text.

HN stores comment bodies as HTML. Inside links, '/' is escaped as '&#x2F;' and
'&' as '&amp;'. So we unescape before we match, or we miss most links.
"""

from __future__ import annotations

import html
import re

_YT = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/"
    r"(?:watch\?(?:[^\s\"'<>#]*?&)?v=|embed/|shorts/|live/|v/|e/)"
    r"|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_ANCHOR = re.compile(r"<a\s[^>]*?href=\"([^\"]*)\"[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


def extract_ids(raw: str | None) -> list[str]:
    """Return the unique YouTube video IDs in a comment, in order of first use."""
    if not raw:
        return []
    seen: dict[str, None] = {}
    for vid in _YT.findall(html.unescape(raw)):
        seen.setdefault(vid, None)
    return list(seen)


def clean_text(raw: str | None) -> str:
    """Turn HN comment HTML into readable plain text. Links become their full URL."""
    if not raw:
        return ""
    s = raw.replace("<p>", "\n\n")
    s = _ANCHOR.sub(lambda m: " " + m.group(1) + " ", s)
    s = _TAG.sub("", s)
    s = html.unescape(s)
    s = _SPACES.sub(" ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    return _BLANKS.sub("\n\n", s).strip()


def own_text(raw: str | None) -> str:
    """The commenter's own words: the comment with every URL removed."""
    s = _URL.sub(" ", clean_text(raw))
    return " ".join(s.split())


def excerpt(text: str, limit: int = 280) -> str:
    """Cut text at a word boundary and add an ellipsis if it was cut."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"
