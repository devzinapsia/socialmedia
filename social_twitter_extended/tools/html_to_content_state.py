"""Convert the HTML of the Odoo editor into the `content_state` of the X Articles API.

Format (POST /2/articles/draft, `ArticleCreateDraftContentState` in the X API
OpenAPI spec). It looks like the DraftJS raw state, but it is NOT the same:
snake_case keys, and `entities` is a list, not an `entityMap` dict::

    {
        "blocks": [{
            "text": "Hello world",
            "type": "unstyled",  # header-one/two/three, (un)ordered-list-item, blockquote
            "inline_style_ranges": [{"offset": 0, "length": 5, "style": "bold"}],
            "entity_ranges": [{"key": 0, "offset": 6, "length": 5}],  # key: index in entities
        }],
        "entities": [{
            "key": "0",
            "value": {"type": "link", "mutability": "mutable", "data": {"url": "https://..."}},
        }],
    }

Supported: paragraphs, bold, italic, strikethrough, headings (h1, h2, h3;
h4-h6 become header-three, X has no deeper level), links, bulleted and
numbered lists, and quotes (X has a blockquote block type).

Not supported (flattened or dropped, see `_convert_block`):
- nested lists: X blocks have no depth, the items are flattened in order;
- code (`pre`): kept as plain text in a paragraph (X only takes code as a
  markdown atomic block, not handled here);
- tables: one paragraph per row, cells separated by " | ";
- images, horizontal rules, embedded media: dropped (they need atomic
  blocks with uploaded media, only the cover image is supported);
- underline, colors, fonts, alignment: dropped, X has no such style.

Offsets and lengths are counted in UTF-16 code units, like the JavaScript
strings DraftJS is built on (an emoji counts as 2).
"""

import re

from lxml import html as lxml_html

HEADER_TYPES = {
    "h1": "header-one",
    "h2": "header-two",
    "h3": "header-three",
    "h4": "header-three",
    "h5": "header-three",
    "h6": "header-three",
}
LIST_ITEM_TYPES = {"ul": "unordered-list-item", "ol": "ordered-list-item"}
BOLD_TAGS = {"b", "strong"}
ITALIC_TAGS = {"i", "em"}
STRIKETHROUGH_TAGS = {"s", "strike", "del"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "figcaption",
    "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "nav", "ol", "p", "pre", "section", "table", "tbody", "thead", "tfoot", "tr", "ul",
}
# Content never rendered as text
SKIPPED_TAGS = {"img", "hr", "script", "style", "video", "iframe", "svg", "picture"}

WHITESPACE_RE = re.compile(r"[ \t\r\n\f\v]+")
BOLD_STYLE_RE = re.compile(r"font-weight\s*:\s*(bold|bolder|[6-9]00)", re.I)
ITALIC_STYLE_RE = re.compile(r"font-style\s*:\s*italic", re.I)
STRIKETHROUGH_STYLE_RE = re.compile(r"text-decoration[^;]*line-through", re.I)


def _utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


class _BlockBuilder:
    """Text of one block, as runs of (text, styles, link url)."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.runs = []

    @property
    def _ends_with_space(self):
        text = "".join(run[0] for run in self.runs)
        return not text or text[-1] in " \n"

    def add_text(self, text, styles, link, preserve_whitespace=False):
        if not text:
            return
        if not preserve_whitespace:
            # HTML rendering: runs of whitespace collapse into a single space
            text = WHITESPACE_RE.sub(" ", text)
            if text.startswith(" ") and self._ends_with_space:
                text = text[1:]
        if text:
            self.runs.append((text, frozenset(styles), link))

    def add_line_break(self):
        # Soft line break inside the block (<br>): drop the space before it
        if self.runs and self.runs[-1][0].endswith(" "):
            text, styles, link = self.runs[-1]
            self.runs[-1] = (text[:-1], styles, link)
        self.runs.append(("\n", frozenset(), None))

    def _trimmed_runs(self):
        runs = [list(run) for run in self.runs if run[0]]
        while runs and not runs[0][0].lstrip(" \n"):
            runs.pop(0)
        while runs and not runs[-1][0].rstrip(" \n"):
            runs.pop()
        if runs:
            runs[0][0] = runs[0][0].lstrip(" \n")
            runs[-1][0] = runs[-1][0].rstrip(" \n")
        return runs

    def build(self, entities):
        """Return the block dict (or None when it has no text), adding its links to `entities`."""
        runs = self._trimmed_runs()
        text = "".join(run[0] for run in runs)
        if not text.strip():
            return None

        style_spans = {}  # style -> list of [offset, end]
        link_spans = []  # [offset, end, url]
        offset = 0
        for run_text, styles, link in runs:
            end = offset + _utf16_length(run_text)
            for style in styles:
                spans = style_spans.setdefault(style, [])
                if spans and spans[-1][1] == offset:
                    spans[-1][1] = end
                else:
                    spans.append([offset, end])
            if link:
                if link_spans and link_spans[-1][1] == offset and link_spans[-1][2] == link:
                    link_spans[-1][1] = end
                else:
                    link_spans.append([offset, end, link])
            offset = end

        inline_style_ranges = [
            {"offset": start, "length": end - start, "style": style}
            for style in ("bold", "italic", "strikethrough")
            for start, end in style_spans.get(style, [])
        ]
        entity_ranges = []
        for start, end, url in link_spans:
            entities.append({
                "key": str(len(entities)),
                "value": {"type": "link", "mutability": "mutable", "data": {"url": url}},
            })
            entity_ranges.append({"key": len(entities) - 1, "offset": start, "length": end - start})
        return {
            "text": text,
            "type": self.block_type,
            "inline_style_ranges": inline_style_ranges,
            "entity_ranges": entity_ranges,
        }


class _Converter:

    def __init__(self):
        self.builders = []

    def _new_block(self, block_type):
        builder = _BlockBuilder(block_type)
        self.builders.append(builder)
        return builder

    # Containers: a mix of block elements and loose inline content
    def _convert_container(self, element):
        loose = None  # implicit paragraph gathering the inline content between blocks
        if element.text and element.text.strip():
            loose = self._new_block("unstyled")
            loose.add_text(element.text, set(), None)
        for child in element:
            tag = _tag(child)
            if not tag:
                pass  # comment: only its tail is content
            elif tag in BLOCK_TAGS:
                self._convert_block(child)
                loose = None
            elif tag not in SKIPPED_TAGS:
                if loose is None:
                    loose = self._new_block("unstyled")
                self._convert_inline(child, loose, set(), None)
            if child.tail and child.tail.strip():
                if loose is None:
                    loose = self._new_block("unstyled")
                loose.add_text(child.tail, set(), None)

    def _convert_block(self, element):
        tag = _tag(element)
        if tag in HEADER_TYPES:
            self._convert_inline_content(element, self._new_block(HEADER_TYPES[tag]))
        elif tag == "p":
            self._convert_inline_content(element, self._new_block("unstyled"))
        elif tag in LIST_ITEM_TYPES:
            self._convert_list(element, LIST_ITEM_TYPES[tag])
        elif tag == "li":
            # <li> outside of a list: plain paragraph
            self._convert_inline_content(element, self._new_block("unstyled"))
        elif tag == "blockquote":
            # One quote block; inner paragraphs become line breaks
            self._convert_inline_content(element, self._new_block("blockquote"))
        elif tag == "pre":
            # Not supported: code is kept as plain text in a paragraph
            self._new_block("unstyled").add_text(element.text_content(), set(), None, preserve_whitespace=True)
        elif tag == "table":
            # Not supported: one paragraph per row, cells separated by " | "
            for row in element.iter("tr"):
                cells = [WHITESPACE_RE.sub(" ", cell.text_content()).strip()
                         for cell in row if _tag(cell) in ("td", "th")]
                self._new_block("unstyled").add_text(" | ".join(cell for cell in cells if cell), set(), None)
        elif tag in SKIPPED_TAGS:
            # Not supported: images and horizontal rules need atomic blocks
            return
        else:
            self._convert_container(element)

    def _convert_list(self, element, item_type):
        for child in element:
            tag = _tag(child)
            if tag == "li":
                builder = self._new_block(item_type)
                nested_lists = []
                self._convert_inline_content(child, builder, nested_lists=nested_lists)
                # Not supported: X blocks have no depth, nested items are flattened after their parent
                for nested in nested_lists:
                    self._convert_list(nested, LIST_ITEM_TYPES[_tag(nested)])
            elif tag in LIST_ITEM_TYPES:
                self._convert_list(child, LIST_ITEM_TYPES[tag])

    def _convert_inline_content(self, element, builder, nested_lists=None):
        builder.add_text(element.text, set(), None)
        for child in element:
            self._convert_inline(child, builder, set(), None, nested_lists)
            builder.add_text(child.tail, set(), None)

    def _convert_inline(self, element, builder, styles, link, nested_lists=None):
        tag = _tag(element)
        if not tag or tag in SKIPPED_TAGS:
            return
        if tag == "br":
            builder.add_line_break()
            return
        if tag in LIST_ITEM_TYPES and nested_lists is not None:
            nested_lists.append(element)
            return
        if tag in BLOCK_TAGS and builder.runs:
            # Block nested in a block (e.g. <p> in <li> or <blockquote>): new line
            builder.add_line_break()

        styles = set(styles)
        style_attribute = element.get("style") or ""
        if tag in BOLD_TAGS or BOLD_STYLE_RE.search(style_attribute):
            styles.add("bold")
        if tag in ITALIC_TAGS or ITALIC_STYLE_RE.search(style_attribute):
            styles.add("italic")
        if tag in STRIKETHROUGH_TAGS or STRIKETHROUGH_STYLE_RE.search(style_attribute):
            styles.add("strikethrough")
        if tag == "a" and element.get("href"):
            link = element.get("href").strip()

        builder.add_text(element.text, styles, link)
        for child in element:
            self._convert_inline(child, builder, styles, link, nested_lists)
            builder.add_text(child.tail, styles, link)

    def convert(self, html):
        if not html or not html.strip():
            return {"blocks": [], "entities": []}
        root = lxml_html.fragment_fromstring(html, create_parent="div")
        self._convert_container(root)
        entities = []
        blocks = [block for block in (builder.build(entities) for builder in self.builders) if block]
        return {"blocks": blocks, "entities": entities}


def _tag(element):
    tag = element.tag
    # Comments and processing instructions have a function as tag
    return tag.lower() if isinstance(tag, str) else ""


def html_to_content_state(html):
    """Return the X Articles `content_state` dict of the HTML `html`."""
    return _Converter().convert(html)
