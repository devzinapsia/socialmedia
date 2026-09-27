from odoo.tests import TransactionCase, tagged

from ..tools.html_to_content_state import html_to_content_state


@tagged("post_install", "-at_install")
class TestHtmlToContentState(TransactionCase):

    def _single_block(self, html):
        content_state = html_to_content_state(html)
        self.assertEqual(len(content_state["blocks"]), 1, content_state)
        return content_state["blocks"][0], content_state["entities"]

    def test_simple_paragraph(self):
        self.assertEqual(html_to_content_state("<p>Hello  world</p>"), {
            "blocks": [{
                "text": "Hello world",
                "type": "unstyled",
                "inline_style_ranges": [],
                "entity_ranges": [],
            }],
            "entities": [],
        })

    def test_bold_and_italic_in_paragraph(self):
        block, _entities = self._single_block(
            "<p>Plain <strong>bold <em>both</em></strong> and <em>italic</em></p>")
        self.assertEqual(block["text"], "Plain bold both and italic")
        self.assertEqual(block["type"], "unstyled")
        self.assertEqual(block["inline_style_ranges"], [
            {"offset": 6, "length": 9, "style": "bold"},
            {"offset": 11, "length": 4, "style": "italic"},
            {"offset": 20, "length": 6, "style": "italic"},
        ])

    def test_headings(self):
        content_state = html_to_content_state(
            "<h1>One</h1><h2>Two</h2><h3>Three</h3><h4>Four</h4>")
        self.assertEqual(
            [(block["type"], block["text"]) for block in content_state["blocks"]],
            [("header-one", "One"), ("header-two", "Two"),
             ("header-three", "Three"), ("header-three", "Four")])

    def test_bulleted_list(self):
        content_state = html_to_content_state("<ul><li>First</li><li><b>Second</b></li></ul>")
        blocks = content_state["blocks"]
        self.assertEqual([(block["type"], block["text"]) for block in blocks],
                         [("unordered-list-item", "First"), ("unordered-list-item", "Second")])
        self.assertEqual(blocks[1]["inline_style_ranges"], [{"offset": 0, "length": 6, "style": "bold"}])

    def test_numbered_list(self):
        content_state = html_to_content_state("<ol><li><p>First</p></li><li>Second</li></ol>")
        self.assertEqual(
            [(block["type"], block["text"]) for block in content_state["blocks"]],
            [("ordered-list-item", "First"), ("ordered-list-item", "Second")])

    def test_link(self):
        block, entities = self._single_block(
            '<p>Visit <a href="https://www.zinapsia.com">our <b>site</b></a> now</p>')
        self.assertEqual(block["text"], "Visit our site now")
        self.assertEqual(block["entity_ranges"], [{"key": 0, "offset": 6, "length": 8}])
        self.assertEqual(block["inline_style_ranges"], [{"offset": 10, "length": 4, "style": "bold"}])
        self.assertEqual(entities, [{
            "key": "0",
            "value": {"type": "link", "mutability": "mutable", "data": {"url": "https://www.zinapsia.com"}},
        }])

    def test_offsets_are_utf16(self):
        # An emoji is 2 UTF-16 code units, like in the JavaScript strings of DraftJS
        block, _entities = self._single_block("<p>🙂 <b>x</b></p>")
        self.assertEqual(block["inline_style_ranges"], [{"offset": 3, "length": 1, "style": "bold"}])

    def test_line_breaks_nested_lists_and_empty_paragraphs(self):
        content_state = html_to_content_state(
            "<p>Line 1<br>Line 2</p><p><br></p><!-- note -->"
            "<ul><li>Parent<ul><li>Child</li></ul></li></ul>")
        self.assertEqual(
            [(block["type"], block["text"]) for block in content_state["blocks"]],
            [("unstyled", "Line 1\nLine 2"),
             ("unordered-list-item", "Parent"),
             ("unordered-list-item", "Child")])

    def test_unsupported_content_is_flattened(self):
        content_state = html_to_content_state(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
            "<pre>code  kept</pre><p><img src='/a.png'/>Text</p><hr/>")
        self.assertEqual(
            [(block["type"], block["text"]) for block in content_state["blocks"]],
            [("unstyled", "A | B"), ("unstyled", "1 | 2"), ("unstyled", "code  kept"), ("unstyled", "Text")])

    def test_empty_body(self):
        self.assertEqual(html_to_content_state("<p><br></p>"), {"blocks": [], "entities": []})
        self.assertEqual(html_to_content_state(False), {"blocks": [], "entities": []})
