"""A small, dependency-free document model for parsing fetched HTML.

Source adapters fetch a page (live or recorded) and parse its HTML with
pure functions built on this module, so parsing can be tested against
recorded pages without a browser. It supports the CSS selector subset the
adapters use: tag names, ``.class``, ``#id``, ``[attr]``, ``[attr=v]``,
``[attr*=v]``, ``[attr^=v]``, ``[attr$=v]``, comma-separated alternatives
and descendant combinators. ``Element.text`` approximates a browser's
``innerText``: block elements break lines, whitespace collapses, and script
and style content is left out.

A browser decides line breaks and hidden text from CSS, which this model
cannot see, so the live fetcher marks each element whose computed display
differs from its tag's default with ``data-display`` ("block", "inline" or
"none") before it serialises the page. Without marks, tag defaults apply.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)
_NO_TEXT = frozenset({"script", "style", "noscript", "template", "svg", "head"})
BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "dd", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
        "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
        "ul", "br", "option", "select",
    }
)
# A start tag of the key implicitly closes an open element of the value set,
# searching no further up than the listed boundaries.
_IMPLICIT_CLOSE: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "li": (frozenset({"li"}), frozenset({"ul", "ol"})),
    "dt": (frozenset({"dt", "dd"}), frozenset({"dl"})),
    "dd": (frozenset({"dt", "dd"}), frozenset({"dl"})),
    "tr": (frozenset({"tr", "td", "th"}), frozenset({"table", "tbody", "thead", "tfoot"})),
    "td": (frozenset({"td", "th"}), frozenset({"tr", "table"})),
    "th": (frozenset({"td", "th"}), frozenset({"tr", "table"})),
    "option": (frozenset({"option"}), frozenset({"select", "datalist"})),
}
_CLOSES_PARAGRAPH = frozenset(
    {
        "address", "article", "aside", "blockquote", "div", "dl", "fieldset",
        "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
        "main", "nav", "ol", "p", "pre", "section", "table", "ul",
    }
)


@dataclass(eq=False)
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element | str] = field(default_factory=list, repr=False)
    parent: Element | None = field(default=None, repr=False)

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> frozenset[str]:
        return frozenset((self.attrs.get("class") or "").split())

    def iter(self) -> Iterator[Element]:
        """Every descendant element, in document order."""
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.iter()

    def ancestors(self) -> Iterator[Element]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def select(self, selector: str) -> list[Element]:
        alternatives = _parse_selector(selector)
        return [
            element
            for element in self.iter()
            if any(_matches_chain(element, chain) for chain in alternatives)
        ]

    def select_one(self, selector: str) -> Element | None:
        found = self.select(selector)
        return found[0] if found else None

    def matches(self, selector: str) -> bool:
        return any(_matches_chain(self, chain) for chain in _parse_selector(selector))

    def closest(self, selector: str) -> Element | None:
        """This element or its nearest ancestor that matches the selector."""
        alternatives = _parse_selector(selector)
        for node in (self, *self.ancestors()):
            if node.tag != "#document" and any(
                _matches_chain(node, chain) for chain in alternatives
            ):
                return node
        return None

    @property
    def text(self) -> str:
        """Visible text with one line per block, like a browser's innerText.

        Like innerText, an element inside hidden content returns all of its
        text run together instead (its textContent).
        """
        if any(
            node.attrs.get("data-display") == "none" for node in (self, *self.ancestors())
        ):
            return "".join(_all_strings(self))
        parts: list[str] = []
        _collect_text(self, parts)
        lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
        return "\n".join(line for line in lines if line)


def _all_strings(element: Element) -> Iterator[str]:
    for child in element.children:
        if isinstance(child, str):
            yield child
        else:
            yield from _all_strings(child)


def _is_block(element: Element) -> bool:
    display = element.attrs.get("data-display")
    if display in {"block", "inline"}:
        return display == "block"
    return element.tag in BLOCK_TAGS


def _collect_text(element: Element, parts: list[str]) -> None:
    if element.tag in _NO_TEXT:
        return
    block = _is_block(element)
    if block:
        parts.append("\n")
    for child in element.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.attrs.get("data-display") != "none":
            _collect_text(child, parts)
    if block:
        parts.append("\n")


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document")
        self.stack: list[Element] = [self.root]

    def _close_implicitly(self, tag: str) -> None:
        if tag in _CLOSES_PARAGRAPH:
            self._pop_to({"p"}, boundaries=frozenset({"#document"}))
        rule = _IMPLICIT_CLOSE.get(tag)
        if rule:
            self._pop_to(rule[0], boundaries=rule[1])

    def _pop_to(self, tags, *, boundaries: frozenset[str]) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            name = self.stack[index].tag
            if name in boundaries:
                return
            if name in tags:
                del self.stack[index:]
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._close_implicitly(tag)
        element = Element(
            tag,
            {name: value or "" for name, value in attrs},
            parent=self.stack[-1],
        )
        self.stack[-1].children.append(element)
        if tag not in VOID_ELEMENTS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._close_implicitly(tag)
        self.stack[-1].children.append(
            Element(tag, {name: value or "" for name, value in attrs}, parent=self.stack[-1])
        )

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(html: str) -> Element:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


@dataclass(frozen=True)
class _Compound:
    tag: str | None
    ids: tuple[str, ...]
    classes: tuple[str, ...]
    attributes: tuple[tuple[str, str | None, str | None], ...]

    def matches(self, element: Element) -> bool:
        if self.tag and element.tag != self.tag:
            return False
        if any(element.get("id") != value for value in self.ids):
            return False
        if not set(self.classes) <= element.classes:
            return False
        for name, operator, value in self.attributes:
            actual = element.get(name)
            if actual is None:
                return False
            if operator is None:
                continue
            if operator == "=" and actual != value:
                return False
            if operator == "*=" and value not in actual:
                return False
            if operator == "^=" and not actual.startswith(value or ""):
                return False
            if operator == "$=" and not actual.endswith(value or ""):
                return False
        return True


_TAG = re.compile(r"[a-zA-Z][\w-]*|\*")
_PART = re.compile(
    r"#(?P<id>[\w-]+)"
    r"|\.(?P<class>[\w-]+)"
    r"|\[\s*(?P<attr>[\w:-]+)\s*(?:(?P<op>[*^$]?=)\s*"
    r"(?:'(?P<sq>[^']*)'|\"(?P<dq>[^\"]*)\"|(?P<bare>[^\]\s]+)))?\s*\]"
)


def _split_outside_brackets(value: str, separator: str) -> list[str]:
    parts, depth, current = [], 0, []
    for character in value:
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        if depth == 0 and (
            character == separator or (separator == " " and character.isspace())
        ):
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _parse_compound(text: str) -> _Compound:
    tag, ids, classes, attributes = None, [], [], []
    position = 0
    tag_match = _TAG.match(text)
    if tag_match:
        tag = None if tag_match.group(0) == "*" else tag_match.group(0).lower()
        position = tag_match.end()
    while position < len(text):
        match = _PART.match(text, position)
        if not match:
            raise ValueError(f"Unsupported selector: {text!r}")
        if match.group("id"):
            ids.append(match.group("id"))
        elif match.group("class"):
            classes.append(match.group("class"))
        else:
            quoted = (match.group("sq"), match.group("dq"), match.group("bare"))
            value = next((group for group in quoted if group is not None), None)
            attributes.append((match.group("attr").lower(), match.group("op"), value))
        position = match.end()
    return _Compound(tag, tuple(ids), tuple(classes), tuple(attributes))


def _parse_selector(selector: str) -> list[list[_Compound]]:
    return [
        [_parse_compound(part) for part in _split_outside_brackets(alternative, " ")]
        for alternative in _split_outside_brackets(selector, ",")
    ]


def _matches_chain(element: Element, chain: list[_Compound]) -> bool:
    if not chain[-1].matches(element):
        return False
    remaining = chain[:-1]
    for ancestor in element.ancestors():
        if not remaining:
            break
        if remaining[-1].matches(ancestor):
            remaining = remaining[:-1]
    return not remaining


def nearby_text_levels(
    element: Element,
    depth: int = 8,
    max_chars: int = 2_000,
) -> tuple[str | None, list[str]]:
    """The first ``time[datetime]`` value and each ancestor's text, nearest first.

    Listing adapters look for a link's date in its narrowest enclosing
    container, so a wider wrapper with several rows' dates is never read.
    Texts stop after the first one longer than ``max_chars``, which has left
    the row for a section or page wrapper.
    """
    time_value: str | None = None
    levels: list[str] = []
    collecting = True
    for ancestor in list(element.ancestors())[:depth]:
        if ancestor.tag == "#document":
            break
        if time_value is None:
            stamp = ancestor.select_one("time[datetime]")
            if stamp is not None:
                time_value = stamp.get("datetime")
        if collecting:
            text = ancestor.text
            levels.append(text)
            collecting = len(text) <= max_chars
    return time_value, levels
