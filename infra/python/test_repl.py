"""Guard platform structure, layout state and embedded language boundaries."""

import unittest
from pathlib import Path
from typing import ClassVar, cast

import msgspec
from csharp_source import ByteParser, field, text, walk
from csharp_source import parse as csharp_parse
from render_repl import ReplLexicon, prelexer
from renode_model import RenodeData
from tree_sitter import Parser, Query, QueryCursor, Tree
from treesitter import Grammar, build, load, monitor_ranges, problems, queries

ROOT = Path(__file__).resolve().parents[2]


class PlatformTests(unittest.TestCase):
    grammar: ClassVar[Grammar]
    monitor: ClassVar[Grammar]

    @classmethod
    def setUpClass(cls) -> None:
        cls.grammar = load(build(ROOT, 'repl'), 'repl')
        cls.monitor = load(build(ROOT))
        queries(ROOT, cls.grammar, 'repl')

    def parse(self, source: str) -> Tree:
        tree = self.grammar.parse(source.encode())
        self.assertFalse(problems(tree.root_node), str(tree.root_node))
        return tree

    def captures(self, filename: str, source: str) -> dict[str, list[str]]:
        tree = self.parse(source)
        query = Query(self.grammar.language, (ROOT / 'zed/languages/repl' / filename).read_text())
        return {
            name: [text(node) for node in sorted(nodes, key=lambda node: node.start_byte)]
            for name, nodes in QueryCursor(query).captures(tree.root_node).items()
        }

    def test_monitor_comments_are_parent_syntax_and_do_not_enter_resc(self) -> None:
        source = 'bus:\n    init:\n        Tag <0, 4> "register" // annotation\n        // between commands\n        /* platform comment */\n        echo "https://host/{safe}"\nnext:\n'
        tree = self.parse(source)
        self.assertEqual(
            [text(node) for node in walk(tree.root_node, 'comment')],
            ['// annotation', '// between commands', '/* platform comment */'],
        )
        chunks = tuple(walk(tree.root_node, 'monitor_text'))
        self.assertTrue(chunks)
        body = b''.join(node.text or b'' for node in chunks)
        self.assertFalse(problems(self.monitor.parse(body).root_node))
        self.assertEqual([text(field(node, 'name')) for node in walk(tree.root_node, 'entry')], ['bus', 'next'])

    def test_registration_lists_objects_dictionaries_and_irqs(self) -> None:
        source = 'local uart: UART.Example @ { sysbus <0x1000, +0x100>; bus new Point { offset: 0x2000 } } as "serial"\n    enabled: True\n    options: { "clock": 12; 1: [empty, new Clock { frequency: 2 }, .Mode, Kind.Mode,] }\n    [Tx, 1-3] -> cpu#0@[1, 2-4] | gic@8\n    4 -> none\n    target: none\nnext:\n'
        tree = self.parse(source)
        for kind, count in (('registration_item', 2), ('object', 2), ('dictionary', 1), ('irq', 2)):
            self.assertEqual(len(tuple(walk(tree.root_node, kind))), count, kind)

    def test_unicode_identifiers_numbers_keyword_prefixes_and_eof_dedents(self) -> None:
        source = 'resetting: Type.Νέα\n    λ_2: new Thing\n        count: ١٢٣'
        tree = self.parse(source)
        self.assertEqual([text(node) for node in walk(tree.root_node, 'number')], ['١٢٣'])
        self.assertEqual(len(tuple(walk(tree.root_node, 'block_end'))), 2)
        data = msgspec.json.decode((ROOT / 'generated/renode.json').read_bytes(), type=RenodeData)
        for word in (item.name for item in data.keywords):
            with self.subTest(word=word):
                self.assertTrue(problems(self.grammar.parse((word + ':\n').encode()).root_node))

    def test_multiline_strings_protect_comments_braces_and_escaped_delimiters(self) -> None:
        source = "p:\n    script: '''\n# Python\ntext = \"// { /* } */\"\nprint(\"\\'''\")\n'''\n    other: \"escaped \\\" // stays in string\"\nnext:\n"
        tree = self.parse(source)
        self.assertEqual(len(tuple(walk(tree.root_node, 'multiline_string'))), 1)
        self.assertEqual(tuple(walk(tree.root_node, 'comment')), ())
        self.assertEqual(len(tuple(walk(tree.root_node, 'entry'))), 2)

    def test_parent_comments_are_space_sensitive_and_urls_remain_monitor_paths(self) -> None:
        source = 'p:\n    init:\n        include @https://example.org/a.resc\n        echo "// literal"\n// dedented comment\n    enabled: true\n'
        tree = self.parse(source)
        self.assertEqual([text(node) for node in walk(tree.root_node, 'comment')], ['// dedented comment'])
        captures = self.captures('injections.scm', source)
        self.assertIn('https://example.org', ''.join(captures['injection.content']))
        self.assertNotIn('// dedented comment', ''.join(captures['injection.content']))
        self.assertTrue(problems(self.grammar.parse(b'p: { value: 1\t// not a comment\n}').root_node))

    def test_injection_matches_keep_fragments_and_blocks_separate(self) -> None:
        source = "p:\n    init:\n        echo \"a\" // parent\n        // between\n        echo \"b\"\n    reset:\n        echo \"c\"\n    script: '''print(\"Python\")'''\n    other: '''opaque'''\n"
        tree = self.parse(source)
        query = Query(self.grammar.language, (ROOT / 'zed/languages/repl/injections.scm').read_text())
        matches = QueryCursor(query).matches(tree.root_node)
        groups = monitor_ranges(ROOT, self.grammar, tree)
        self.assertEqual(len(groups), 2)
        contents: list[str] = [''.join(text(node) for node in nodes) for nodes in groups]
        for nodes in groups:
            self.assertFalse(problems(self.monitor.parse_ranges(source.encode(), nodes).root_node))
        self.assertIn('echo "a"', contents[0])
        self.assertIn('echo "b"', contents[0])
        self.assertNotIn('//', contents[0])
        self.assertNotIn('echo "c"', contents[0])
        python = [
            text(node)
            for pattern, captures in matches
            if query.pattern_settings(pattern)['injection.language'] == 'python'
            for node in captures['injection.content']
        ]
        self.assertEqual(python, ['print("Python")'])

    def test_monitor_fragments_identify_the_same_host_across_comment_gaps(self) -> None:
        source = (ROOT / 'infra/zed/review.repl').read_text()
        tree = self.parse(source)
        body = next(walk(tree.root_node, 'monitor_body'))
        fragments = tuple(walk(body, 'monitor_text'))
        query = Query(self.grammar.language, (ROOT / 'zed/languages/repl/injections.scm').read_text())
        # Zed queries changed regions separately. Each fragment must identify its
        # containing body, so it can merge ranges independently of query batching.
        for fragment in fragments:
            cursor = QueryCursor(query)
            cursor.set_byte_range(fragment.start_byte, fragment.end_byte)
            matches = cursor.matches(tree.root_node)
            hosts = [host for _, captures in matches for host in captures.get('injection.host', [])]
            self.assertTrue(hosts, 'Zed needs a containing host for each monitor fragment')
            self.assertTrue(all(host == body for host in hosts))

    def test_review_fixture_exercises_both_injections_and_both_block_modes(self) -> None:
        source = (ROOT / 'infra/zed/review.repl').read_text()
        tree = self.parse(source)
        query = Query(self.grammar.language, (ROOT / 'zed/languages/repl/injections.scm').read_text())
        groups = monitor_ranges(ROOT, self.grammar, tree)
        python_count = 0
        for nodes in groups:
            inner = self.monitor.parse_ranges(source.encode(), nodes)
            self.assertFalse(problems(inner.root_node), str(inner.root_node))
            python_count += len(tuple(walk(inner.root_node, 'python_body')))
        for pattern, _captures in QueryCursor(query).matches(tree.root_node):
            if query.pattern_settings(pattern)['injection.language'] == 'python':
                python_count += 1
        self.assertEqual((len(groups), python_count), (4, 3))
        self.assertIn('after', self.captures('outline.scm', source)['name'])

    def test_incremental_edit_restores_layout_and_delimiter_state(self) -> None:
        samples = (
            ('p:\n    value: 1\nnext:\n', '    nested: new Thing\n        flag: True\n', 'next:'),
            ("p:\n    script: '''print(1)'''\nnext:\n", '\ntext = "/* { } */"\n', 'print(1)'),
            ('p: { init: { echo "a" }; value: 1 }\nnext:\n', '\n// comment\necho "b"\n', 'echo "a"'),
        )
        for source, addition, marker in samples:
            with self.subTest(source=source):
                encoded = source.encode()
                offset = encoded.index(marker.encode())
                prefix = encoded[:offset]
                point = (prefix.count(b'\n'), len(prefix.rsplit(b'\n', 1)[-1]))
                replacement = addition.encode()
                after = (
                    point
                    if not replacement
                    else (
                        point[0] + replacement.count(b'\n'),
                        len(replacement.rsplit(b'\n', 1)[-1]) if b'\n' in replacement else point[1] + len(replacement),
                    )
                )
                parser = Parser(self.grammar.language)
                old = cast(ByteParser, parser).parse(encoded)
                old.edit(
                    start_byte=offset,
                    old_end_byte=offset,
                    new_end_byte=offset + len(replacement),
                    start_point=point,
                    old_end_point=point,
                    new_end_point=after,
                )
                changed = encoded[:offset] + replacement + encoded[offset:]
                incremental = cast(ByteParser, parser).parse(changed, old)
                fresh = self.grammar.parse(changed)
                self.assertFalse(problems(fresh.root_node), str(fresh.root_node))
                self.assertEqual(str(incremental.root_node), str(fresh.root_node))

    def test_malformed_layout_strings_and_comment_placement_are_rejected(self) -> None:
        for source in (
            '    p:\n',
            'p:\n  value: 1\n',
            'p:\n\tvalue: 1\n',
            'p: { value: "unclosed }',
            "p:\n    script: '''unclosed",
            'p:\n/* block */ value: 1\n',
            'p: { value: [none] }',
            'p: { value: { "a": none } }',
            'p: { value: 1',
        ):
            with self.subTest(source=source):
                self.assertTrue(problems(self.grammar.parse(source.encode()).root_node))


class PlatformExtractionTests(unittest.TestCase):
    def test_source_provenance_and_unicode_rules_are_preserved(self) -> None:
        data = msgspec.json.decode((ROOT / 'generated/repl.json').read_bytes(), type=ReplLexicon)
        self.assertEqual(data.indent.value, 4)
        self.assertIn('PreLexer.cs', data.indent.source.path)
        self.assertIn(r'\p{L}', data.rules['Identifier'].pattern)
        self.assertIn(r'\p{Nd}', data.rules['Number'].pattern)

    def test_unrecognised_prelexer_constants_fail_loudly(self) -> None:
        source = 'class PreLexer { const int SpacesPerIndent = Compute(); }'
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            _ = prelexer(csharp_parse('renode', 'PreLexer.cs', source.encode()))


if __name__ == '__main__':
    _ = unittest.main()
