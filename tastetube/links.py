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


# Playlists. Only creator playlists ('PL...') are courses and series. Mixes ('RD'),
# albums ('OLAK5uy_') and uploads ('UU') are not things people recommend as a course.
_PLAYLIST = re.compile(
    r"youtube(?:-nocookie)?\.com/[^\s\"'<>]*?[?&]list=(PL[A-Za-z0-9_-]{16,34})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
# A description line that starts a chapter: "12:34 Title", "1:02:03 - Title", "(0:00) Intro".
_CHAPTER = re.compile(r"^\s*[\[(]?((?:\d{1,2}:)?\d{1,2}:\d{2})[\])]?\s*[-–—:|]?\s+(.+?)\s*$")


def _unique(items) -> list[str]:
    return list(dict.fromkeys(items))


def extract_ids(raw: str | None) -> list[str]:
    """Return the unique YouTube video IDs in a comment, in order of first use."""
    if not raw:
        return []
    return _unique(_YT.findall(html.unescape(raw)))


def extract_playlists(raw: str | None) -> list[str]:
    """Return the unique playlist (course or series) IDs in a comment."""
    if not raw:
        return []
    return _unique(_PLAYLIST.findall(html.unescape(raw)))


def is_course(item_id: str) -> bool:
    """Video IDs are exactly 11 characters. Playlist IDs are 18 or more."""
    return len(item_id) > 11


def parse_chapters(description: str | None) -> list[tuple[int, str]]:
    """Chapters from a YouTube description. YouTube's own rule: first at 0:00, 3 or more."""
    out: list[tuple[int, str]] = []
    for line in (description or "").splitlines():
        m = _CHAPTER.match(line)
        if not m:
            continue
        parts = [int(p) for p in m.group(1).split(":")]
        sec = sum(p * 60**i for i, p in enumerate(reversed(parts)))
        if out and sec <= out[-1][0]:
            continue
        out.append((sec, m.group(2)[:90]))
    if len(out) < 3 or out[0][0] != 0:
        return []
    return out


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
