"""Guards against a silent, page-breaking interaction in index.html.

The DC runtime (support.js, generated from dc-runtime and marked "do not
edit") rewrites camelCase *HTML attribute names* into `sc-camel-kebab-case`
so they survive the HTML parser, which lowercases everything. It does that
with one regex over the whole template:

    /(\\s)([a-z]+[A-Z][A-Za-z0-9]*)(\\s*=)/g

Whitespace, a camelCase word, an `=`. That describes an HTML attribute — and
equally describes a JavaScript assignment. The rewrite runs across the entire
`<x-dc>` block including `<script>` bodies, so

    var prefersDark = ...      became      var sc-camel-prefers-dark = ...

which is a SyntaxError. It threw on every page load, three times, from inside
React's commit phase, which made it look like a React bug rather than a
mangled inline script.

The app's own logic is exempt: the `<script data-dc-script>` block after
`</x-dc>` is extracted before encoding, so its ~250 camelCase assignments are
untouched. Only inline scripts *inside* the template region are at risk.

Fixing support.js is not an option here -- it is a build artefact whose source
lives in another repo -- so this test holds the line from our side.
"""
import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The exact regex from support.js (CAMEL_ATTR_RE).
CAMEL_ATTR_RE = re.compile(r"(\s)([a-z]+[A-Z][A-Za-z0-9]*)(\s*=)")
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


class TemplateEncodingTest(unittest.TestCase):
    def setUp(self):
        self.path = REPO_ROOT / "index.html"
        self.html = self.path.read_text()

    def _template_region(self):
        """Only what the encoder actually touches.

        First opening tag, LAST closing tag -- the same rule support.js uses
        (a regex for the open, `lastIndexOf` for the close). A naive
        `index()` on the close stops at the first mention of the tag in a
        comment, which silently shrinks the region to nothing and makes this
        guard pass while measuring almost no code. That happened once.
        """
        open_match = re.search(r"<x-dc(?:\s[^>]*)?>", self.html)
        self.assertIsNotNone(open_match, "no DC template block in index.html")
        start = open_match.end()
        end = self.html.rindex("</x-dc" + ">")
        self.assertGreater(end, start, "DC template block is empty or inverted")
        return self.html[start:end], self.html[:start].count("\n") + 1

    def test_the_template_region_is_still_where_we_think(self):
        # If the page stops using the DC runtime, this test is measuring
        # nothing and should be deleted rather than left quietly passing.
        self.assertIn("support.js", self.html)
        region, _line = self._template_region()
        # Big enough to plausibly be the whole template, and it must actually
        # contain the inline script this bug lived in.
        self.assertGreater(len(region), 10000)
        self.assertIn("data-theme", region)
        self.assertTrue(INLINE_SCRIPT_RE.search(region), "no inline scripts found to check")

    def test_no_inline_script_in_the_template_trips_the_camel_rewriter(self):
        region, base_line = self._template_region()
        offenders = []
        for script in INLINE_SCRIPT_RE.finditer(region):
            body = script.group(1)
            script_line = base_line + region[: script.start()].count("\n")
            for match in CAMEL_ATTR_RE.finditer(body):
                offenders.append(
                    "index.html:%d  %s"
                    % (script_line + body[: match.start()].count("\n"), match.group(0).strip())
                )

        self.assertEqual(
            offenders,
            [],
            "camelCase assignment inside an inline <script> in the <x-dc> template.\n"
            "The DC runtime will rewrite it to sc-camel-kebab-case and the script\n"
            "will throw SyntaxError on every page load. Use a lowercase name, or\n"
            "inline the expression so there is no assignment:\n  " + "\n  ".join(offenders),
        )

    def test_the_regex_here_still_matches_the_bug_it_was_written_for(self):
        # Keeps the guard honest: if this stops matching, the test above has
        # quietly become a no-op.
        self.assertTrue(CAMEL_ATTR_RE.search(" var prefersDark = true"))
        self.assertIsNone(CAMEL_ATTR_RE.search(" var stored = null"))


if __name__ == "__main__":
    unittest.main()
